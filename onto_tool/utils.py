"""Utility methods shared by multiple subcommands"""
import logging
import re
from glob import glob
from os.path import isdir, isfile, join
import sys

from rdflib import ConjunctiveGraph, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD
from rdflib.plugins.parsers.notation3 import BadSyntax
from rdflib.util import guess_format


def parse_rdf(g: Graph, onto_file: str, rdf_format: str = None):
    """Import local RDF content into the graph, report parse error."""
    try:
        g.parse(onto_file, format=rdf_format if rdf_format is not None else guess_format(
            onto_file))
    except BadSyntax as se:
        # noinspection PyProtectedMember
        # Need to poke into parse exception
        # pylint: disable=W0212
        text, why = (se._str.decode('utf-8'), se._why)
        if len(text) > 30:
            text = text[0:27] + '...'
        logging.error("Error parsing %s at %d: %s: %s",
                      onto_file, se.lines + 1, why, text)
        sys.exit(1)


def find_single_ontology(g, onto_file):
    """Verify that file has a single ontology defined and return the IRI."""
    ontologies = list(g.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) == 0:
        logging.warning('No ontology definition found in %s', onto_file)
        return None
    if len(ontologies) > 1:
        logging.error('Multiple ontologies defined in %s, skipping',
                      onto_file)
        return None

    ontology = ontologies[0]
    logging.debug('%s found in %s', ontology, onto_file)
    return ontology


def add_defined_by(g, ontology_iri, mode='strict', replace=False, versioned=False):
    """Add rdfs:isDefinedBy to every entity declared by the ontology."""
    if versioned:
        version_iri = next(g.objects(ontology_iri, OWL.versionIRI), None)
        if version_iri is not None:
            ontology_iri = version_iri
    if mode == 'strict':
        selector = """
          FILTER(?dtype IN (
            owl:Class, owl:ObjectProperty, owl:DatatypeProperty,
            owl:AnnotationProperty, owl:Thing
          ))
        """
    else:
        selector = "FILTER(?dtype != owl:Ontology)"

    query = """
        SELECT distinct ?defined ?label ?defBy WHERE {
          ?defined a ?dtype .
          %s
          FILTER(!ISBLANK(?defined))
          FILTER EXISTS {
            ?defined ?anotherProp ?value .
            FILTER (?anotherProp != rdf:type)
          }
          OPTIONAL { ?defined rdfs:isDefinedBy ?defBy }
        }
        """ % selector

    definitions = g.query(
        query,
        initNs={'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})
    for d in definitions:
        if d.defBy:
            if d.defBy == ontology_iri:
                logging.debug('%s already defined by %s',
                              d.defined, ontology_iri)
            else:
                if replace:
                    logging.debug(
                        'Replaced definedBy for %s to %s',
                        d.defined, ontology_iri)
                    g.remove((d.defined, RDFS.isDefinedBy, d.defBy))
                    g.add((d.defined, RDFS.isDefinedBy, ontology_iri))
                else:
                    logging.warning('%s defined by %s instead of %s',
                                    d.defined, d.defBy, ontology_iri)
        else:
            logging.debug('Added definedBy to %s', d.defined)
            g.add((d.defined, RDFS.isDefinedBy, ontology_iri))


def expand_file_ref(path):
    """Expand file reference to a list of paths.

    If a file is provided, return as is. If a directory, return all .owl
    files in the directory, otherwise interpret path as a glob pattern.
    """
    if isfile(path):
        return [path]
    if isdir(path):
        return glob(join(path, '*.owl'))
    return glob(path)


def strip_versions(g, ontology=None):
    """Remove versions (numeric or X.x.x placeholder) from imports."""
    # Gather current dependencies
    ontologies = [ontology] if ontology else list(
        g.subjects(RDF.type, OWL.Ontology))
    for o in ontologies:
        current_deps = g.objects(o, OWL.imports)
        pattern = re.compile(
            '^(.*?)((\\d+|[Xx])\\.(\\d+|[Xx])\\.(\\d+|[Xx]))?$')
        for d in current_deps:
            match = pattern.match(str(d))
            if match.group(2):
                logging.debug('Removing version for %s', d)
                g.remove((o, OWL.imports, d))
                g.add((o, OWL.imports, URIRef(match.group(1))))


def version_sensitive_match(reference, ontologies, versions):
    """Check if reference is in ontologies, ignoring version."""
    match = re.match(r'^(.*?)((\d+|[Xx])\.(\d+|[Xx])\.(\d+|[Xx]))?$',
                     str(reference))
    ref_without_version = match.group(1)
    return URIRef(ref_without_version) in ontologies or reference in versions


def clean_merge_artifacts(g, iri, version):
    """Remove all existing ontology declaration, replace with new merged ontology."""
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    versions = set(v for o in ontologies for v in g.objects(o, OWL.versionIRI))
    external_imports = list(
        i for i in g.objects(subject=None, predicate=OWL.imports)
        if not version_sensitive_match(i, ontologies, versions))
    for o in ontologies:
        logging.debug('Removing existing ontology %s', o)
        for t in list(g.triples((o, None, None))):
            g.remove(t)
    logging.info('Creating new ontology %s:%s', iri, version)
    g.add((iri, RDF.type, OWL.Ontology))
    g.add((iri, OWL.versionIRI, URIRef(str(iri) + version)))
    g.add((iri, OWL.versionInfo, Literal(
        "Created by merge tool.", datatype=XSD.string)))
    for i in external_imports:
        logging.debug('Transferring external dependency %s to %s',
                      i, iri)
        g.add((iri, OWL.imports, i))


def perform_export(output, output_format, paths, context=None,
                   remove_dependency_versions=False,
                   merge=None,
                   defined_by=None,
                   retain_defined_by=False,
                   versioned_defined_by=False):
    """
    Export one or more files as a single output.

    Parameters
    ----------
    output: writable stream
        Destination for combined RDF.
    output_format: string
        Serialization format (turtle, nt, xml)
    paths: list
        List of file paths of RDF resources to combine for this export.
    context: string, optional
        If specified, place the exported RDF in the named graph. Output
        format is set to nquads, ignoring the output_format argument.
    merge: tuple, optional
        If a (iri, version) tuple is provided, all owl:Ontology entities
        in the combined graph are removed, and replaced with a single Ontology
        entity with the provided IRI and version.
    defined_by : string, optional
        Creates rdfs:isDefinedBy links for entities declared in the graph
        to the Ontology. If there is either no owl:Ontology defined, or if
        there are multiple ontologies defined, this step will fail.
        If 'strict' is specified, links are added only to owl:Class,
        owl:DatatypeProperty, owl:ObjectProperty and owl:AnnotationProperty
        instances. If 'all' is specified, every entity in the graph is
        annotated.
    retain_defined_by : boolean, optional
        The default (False) functionality is to replace any existing
        rdfs:isDefinedBy annotations with a reference to the new ontology.
        If True, however, existing rdfs:isDefinedBy values are left in place.
    versioned_defined_by : boolean, optional
        The default (False) functionality is to use the ontology IRI for
        rdfs:isDefinedBy annotations.
        If True and a versionIRI is present, use that instead.

    Returns
    -------
    None.

    """
    if context:
        g = ConjunctiveGraph()
        parse_graph = g.get_context(context)
        output_format = 'nquads'
    else:
        g = Graph()
        parse_graph = g

    for onto_file in [file for ref in paths for file in expand_file_ref(ref)]:
        parse_rdf(parse_graph, onto_file)

    # Remove dep versions
    if remove_dependency_versions:
        strip_versions(parse_graph)

    if merge:
        clean_merge_artifacts(parse_graph, URIRef(merge[0]), merge[1])

    # Add rdfs:isDefinedBy
    if defined_by:
        ontology_iri = find_single_ontology(parse_graph, 'merged graph')
        if ontology_iri is None:
            return
        add_defined_by(parse_graph, ontology_iri,
                       mode=defined_by,
                       replace=not retain_defined_by,
                       versioned=versioned_defined_by)

    serialized = g.serialize(format=output_format)
    output.write(serialized)
