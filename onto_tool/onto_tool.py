"""Toolkit for ontology maintenance and release."""
import io
import logging
import os
import sys
from os.path import join, isdir, isfile, basename, splitext
from glob import glob
import re
import subprocess
import shutil
import gzip
import json
import yaml
import csv
from jsonschema import validate
from typing import Tuple, List
from rdflib import Graph, ConjunctiveGraph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD, Namespace
from rdflib.util import guess_format
from rdflib.plugins.sparql import prepareQuery
from SPARQLWrapper import TURTLE
import pyshacl
from pyparsing import ParseException
from .command_line import configure_arg_parser
from .ontograph import OntoGraf
from .mdutils import Markdown2HTML
from .sparql_utils import create_endpoint, select_query_csv

# f-strings are fine in log messages
# pylint: disable=W1202
# CamelCase variable names are fine
# pylint: disable=C0103


def parse_rdf(g: Graph, onto_file, rdf_format=None):
    from rdflib.plugins.parsers.notation3 import BadSyntax
    try:
        g.parse(onto_file, format=rdf_format if rdf_format is not None else guess_format(onto_file))
    except BadSyntax as se:
        # noinspection PyProtectedMember
        text, why = (se._str.decode('utf-8'), se._why)
        if len(text) > 30:
            text = text[0:27] + '...'
        logging.error("Error parsing %s at %d: %s: %s", onto_file, se.lines + 1, why, text)
        exit(1)


def find_single_ontology(g, onto_file):
    """Verify that file has a single ontology defined and return the IRI."""
    ontologies = list(g.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) == 0:
        logging.warning(f'No ontology definition found in {onto_file}')
        return None
    if len(ontologies) > 1:
        logging.error(f'Multiple ontologies defined in {onto_file}, skipping')
        return None

    ontology = ontologies[0]
    logging.debug(f'{ontology} found in {onto_file}')
    return ontology


def set_version(g, ontology, ontology_iri, version):
    """Add or replace versionIRI for the specified ontology."""
    old_version = next(g.objects(ontology, OWL.versionIRI), None)
    if old_version:
        logging.debug(f'Removing versionIRI {old_version} from {ontology}')
        g.remove((ontology, OWL.versionIRI, old_version))

    version_iri = URIRef(f"{ontology_iri}{version}")
    g.add((ontology, OWL.versionIRI, version_iri))
    logging.info(f'versionIRI {version_iri} added for {ontology}')


def set_version_info(g, ontology, version_info):
    """Add versionInfo for the ontology.

    If versionInfo is not provided, extracts ontology version from versionIRI.
    """
    version_info = version_info if version_info != 'auto' else None
    pattern = re.compile('^(.*?)(\\d+\\.\\d+\\.\\d+)?$')
    version_iri = next(g.objects(ontology, OWL.versionIRI), None)
    version = pattern.match(str(version_iri)).group(2) if version_iri else None
    if not version and not version_info:
        raise Exception(f'No version found for {ontology}, must specify version info')

    old_version_info = next(g.objects(ontology, OWL.versionInfo), None)
    if old_version_info:
        logging.debug(f'Removing previous versionInfo from {ontology}')
        g.remove((ontology, OWL.versionInfo, old_version_info))

    if not version_info:
        version_info = "Version " + version
    g.add((ontology, OWL.versionInfo, Literal(version_info, datatype=XSD.string)))
    logging.info(f'versionInfo "{version_info}" added for {ontology}')


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
                logging.debug(f'{d.defined} already defined by {ontology_iri}')
            else:
                if replace:
                    logging.debug(f'Replaced definedBy for {d.defined} to {ontology_iri}')
                    g.remove((d.defined, RDFS.isDefinedBy, d.defBy))
                    g.add((d.defined, RDFS.isDefinedBy, ontology_iri))
                else:
                    logging.warning(f'{d.defined} defined by {d.defBy}'
                                    f' instead of {ontology_iri}')
        else:
            logging.debug(f'Added definedBy to {d.defined}')
            g.add((d.defined, RDFS.isDefinedBy, ontology_iri))


def update_dependency_versions(g, ontology, versions):
    """Update ontology dependency versions.

    The versions dict maps ontology IRI to their versions.
    Inspect the imports of the current ontology, and if they match
    (ignoring version) any of the ontology provided in the argument,
    update them to the new version.
    """
    # Gather current dependencies
    current_deps = g.objects(ontology, OWL.imports)
    for dv in versions:
        dep, ver = dv
        pattern = re.compile(f'{dep}(\\d+\\.\\d+\\.\\d+)?')
        match = next((c for c in current_deps if pattern.search(str(c))), None)
        if match:
            # Updating current dependency
            current = pattern.search(str(match)).group(1)
            if current:
                logging.debug(f'Removing dependency {current} for {dep}')
                new_version_uri = URIRef(str(match).replace(current, ver))
            else:
                logging.debug(f'Removing unversioned depenendency for {dep}')
                new_version_uri = URIRef(f'{str(match)}{ver}')
            g.remove((ontology, OWL.imports, match))

            g.add((ontology, OWL.imports, new_version_uri))
            logging.info(f'Updated dependency to {new_version_uri}')
        else:
            # New versioned dependency, assuming full URI
            new_version_uri = URIRef(f'{dep}{ver}')
            g.add((ontology, OWL.imports, new_version_uri))
            logging.info(f'Added dependency for {new_version_uri}')


def strip_versions(g, ontology=None):
    """Remove versions (numeric or X.x.x placeholder) from imports."""
    # Gather current dependencies
    ontologies = [ontology] if ontology else list(g.subjects(RDF.type, OWL.Ontology))
    for o in ontologies:
        current_deps = g.objects(o, OWL.imports)
        pattern = re.compile('^(.*?)((\\d+|[Xx])\\.(\\d+|[Xx])\\.(\\d+|[Xx]))?$')
        for d in current_deps:
            match = pattern.match(str(d))
            if match.group(2):
                logging.debug(f'Removing version for {d}')
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
        logging.debug(f'Removing existing ontology {o}')
        for t in list(g.triples((o, None, None))):
            g.remove(t)
    logging.info(f'Creating new ontology {iri}:{version}')
    g.add((iri, RDF.type, OWL.Ontology))
    g.add((iri, OWL.versionIRI, URIRef(str(iri) + version)))
    g.add((iri, OWL.versionInfo, Literal("Created by merge tool.", datatype=XSD.string)))
    for i in external_imports:
        logging.debug(f'Transferring external dependency {i} to {iri}')
        g.add((iri, OWL.imports, i))


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


def serialize_to_output_dir(tools, output, version, file):
    """Serialize ontology file using standard options."""
    base, ext = splitext(basename(file))
    output_file = join(output, f"{base}{version}{ext}")
    logging.debug(f"Serializing {file} to {output}")
    serialize_args = [
        "java",
        "-jar", join(tools, "rdf-toolkit.jar"),
        "-tfmt", "rdf-xml",
        "-sdt", "explicit",
        "-dtd",
        "-ibn",
        "-s", file,
        "-t", output_file]
    subprocess.run(serialize_args)
    return output_file


def replace_patterns_in_file(file, from_pattern, to_string):
    """Replace regex pattern in file contents."""
    with open(file, 'r') as f:
        replaced = re.compile(from_pattern).sub(to_string, f.read())
    with open(file, 'w') as f:
        f.write(replaced)


def copy_if_present(from_loc, to_loc):
    """Copy file to new location if present."""
    if isfile(from_loc):
        shutil.copy(from_loc, to_loc)


def generate_graphic(action, onto_files, endpoint, **kwargs):
    """
    Generate ontology .dot and .png graphic.

    Parameters
    ----------
    action : string
        'ontology' or 'data', depending on the type of graphic requested.
    onto_files : list(string)
        List of paths or glob patterns from which to gather ontologies.
    endpoint : string
        URL of SPARQL endpoint to use for data instead of local ontology files.


    Keyword Parameters
    ------------------
    wee : boolean
        If True, generate a compact ontology graph.
    outpath : string
        Path of directory where graph will be output.
    version : string
        Version to be used in graphic title.
    include: list(string)
        List of ontology URIs to include for schema graph, or named graphs to consider for data graph.
    include_pattern: list(string)
        List of regex against which ontology URIs are matched for inclusion in schema graph, or
        named graphs are matched for inclusion in a data graph.
    exclude: list(string)
        List of ontology URIs to exclude from schema graph, or named graphs to exclude from data graph.
    exclude_pattern: list(string)
        List of regex against which ontology URIs are matched for exclusion from schema graph, or
        named graphs are matched for exclusion from a data graph.
    show_shacl: boolean
        If True, attempt to detect SHACL shapes matching classes and properties.

    Returns
    -------
    None.

    """
    all_files = [file for ref in onto_files for file in expand_file_ref(ref)]
    og = OntoGraf(all_files, repo=endpoint, **kwargs)
    if endpoint and all_files:
        logging.warning('Endpoint specified, ignoring files')
    if action == 'ontology':
        if endpoint:
            og.gather_schema_info_from_repo()
        else:
            og.gather_schema_info_from_files()
        og.create_schema_graf()
    else:
        og.gather_instance_info()
        og.create_instance_graf()


def __perform_export__(output, output_format, paths, context=None,
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
    output.write(serialized.decode(output.encoding))


class VarDict(dict):
    """Dict that performs variable substitution on values."""

    def __init__(self, *args):
        """Initialize."""
        dict.__init__(self, args)

    def __getitem__(self, k):
        """Interpret raw value as template to be substituted with variables."""
        template = dict.__getitem__(self, k)
        return template.format(**self)


BUNDLE_ACTIONS = dict()


def register(name):
    """Register a function as a bundle action"""
    def pass_through(func):
        BUNDLE_ACTIONS[name] = func
        return func
    return pass_through


def __bundle_file_list(action, variables, ignore_target=False):
    """
    Expand a source/target/includes spec into a list of inputFile/outputFile pairs.

    If ignore_target is specified, renaming is ignored and 'outputFile'
    will always be None

    Otherwise, target is assumed to be a directory, which is created if
    it does not exist.

    Parameters
    ----------
    action : dict
        Action definition which contains source, target and (optionally)
        an includes list of patterns.
    variables : dict
        Current variable values to use in substitution.
    ignore_target : bool, optional
        If True, only generate input list.

    Yields
    ------
    dict
        Contains 'inputFile' and 'outputFile' unless ignore_target
        is specified.

    """
    if 'includes' in action:
        # source and target are directories, apply glob
        src_dir = action['source'].format(**variables)
        if not ignore_target:
            tgt_dir = action['target'].format(**variables)
            if not isdir(tgt_dir):
                os.mkdir(tgt_dir)
        else:
            # There are times when
            tgt_dir = None
        for pattern in action['includes']:
            matches = list(glob(os.path.join(src_dir, pattern)))
            if not matches and not any(wildcard in pattern for wildcard in '[]*?'):
                logging.warning('%s not found in %s', pattern, src_dir)
            for input_file in matches:
                if ignore_target:
                    output_file = None
                else:
                    if 'rename' in action:
                        from_pattern = re.compile(
                            action['rename']['from'].format(**variables))
                        to_pattern = action['rename']['to'].format(**variables)
                        output_file = from_pattern.sub(
                            to_pattern,
                            os.path.basename(input_file))
                    else:
                        output_file = os.path.basename(input_file)
                yield dict(inputFile=input_file,
                           outputFile=None if output_file is None else os.path.join(tgt_dir, output_file))
    else:
        yield dict(inputFile=action['source'].format(**variables),
                   outputFile=None if ignore_target else action['target'].format(**variables))


def __bundle_transform_shell__(action, arguments, variables):
    for in_out in __bundle_file_list(action, variables):
        invocation_vars = VarDict()
        invocation_vars.update(variables)
        invocation_vars.update(in_out)
        interpreted_args = [arg.format(**invocation_vars) for arg in arguments]
        logging.debug('Running %s', interpreted_args)
        status = subprocess.run(interpreted_args, capture_output=True)
        if status.stdout:
            logging.debug('stdout for %s is %s', action, status.stdout)
        if status.stderr:
            logging.debug('stderr for %s is %s', action, status.stderr)
        if status.returncode != 0:
            logging.error("Tool %s exited with %d: %s", interpreted_args, status.returncode, status.stderr)
            exit(1)
        if 'replace' in action:
            replace_patterns_in_file(in_out['outputFile'],
                                     action['replace']['from'].format(**invocation_vars),
                                     action['replace']['to'].format(**invocation_vars))


def __bundle_transform_sparql__(action, tool, variables):
    query = tool['query'].format(**variables)
    if isfile(query):
        query_text = open(query, 'r').read()
    else:
        query_text = query

    parsed_query = __parse_update_query__(query_text)

    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        parse_rdf(g, onto_file, rdf_format=rdf_format)

        g.update(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if 'format' in tool:
            rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
        else:
            rdf_format = rdf_format

        g.serialize(destination=in_out['outputFile'], format=rdf_format, encoding='utf-8')

        if 'replace' in action:
            replace_patterns_in_file(in_out['outputFile'],
                                     action['replace']['from'].format(**variables),
                                     action['replace']['to'].format(**variables))


def __parse_update_query__(query_text):
    from rdflib.plugins.sparql.parser import parseUpdate
    from rdflib.plugins.sparql.algebra import translateUpdate
    parsed_query = translateUpdate(parseUpdate(query_text))
    return parsed_query


def __bundle_transform__(action, tools, variables):
    logging.debug('Transform %s', action)
    tool = next((t for t in tools if t['name'] == action['tool']), None)
    if not tool:
        raise Exception('Missing tool ', action['tool'])
    if tool['type'] == 'Java':
        __bundle_transform_shell__(action, ["java", "-jar", tool['jar']] + tool['arguments'], variables)
    elif tool['type'] == 'shell':
        __bundle_transform_shell__(action, tool['arguments'], variables)
    elif tool['type'] == 'sparql':
        __bundle_transform_sparql__(action, tool, variables)
    else:
        raise Exception('Unsupported tool type ', tool['type'])


@register(name="definedBy")
def __bundle_defined_by__(action, variables):
    logging.debug('Add definedBy %s', action)
    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        parse_rdf(g, onto_file, rdf_format)

        # locate ontology
        ontology = find_single_ontology(g, onto_file)
        if not ontology:
            logging.warning(f'Ignoring {onto_file}, no ontology found')
            # copy as unchanged
            shutil.copy(in_out['inputFile'], in_out['outputFile'])
        else:
            add_defined_by(g, ontology,
                           replace=not __boolean_option__(action, 'retainDefinedBy', variables),
                           versioned=__boolean_option__(action, 'versionedDefinedBy', variables))

            g.serialize(destination=in_out['outputFile'],
                        format=rdf_format, encoding='utf-8')
        if 'replace' in action:
            replace_patterns_in_file(in_out['outputFile'],
                                     action['replace']['from'].format(**variables),
                                     action['replace']['to'].format(**variables))


@register(name="copy")
def __bundle_copy__(action, variables):
    logging.debug('Copy %s', action)
    for in_out in __bundle_file_list(action, variables):
        if isfile(in_out['inputFile']):
            shutil.copy(in_out['inputFile'], in_out['outputFile'])
            if 'replace' in action:
                replace_patterns_in_file(in_out['outputFile'],
                                         action['replace']['from'].format(**variables),
                                         action['replace']['to'].format(**variables))


@register(name="move")
def __bundle_move__(action, variables):
    logging.debug('Move %s', action)
    for in_out in __bundle_file_list(action, variables):
        if isfile(in_out['inputFile']):
            shutil.move(in_out['inputFile'], in_out['outputFile'])
            if 'replace' in action:
                replace_patterns_in_file(in_out['outputFile'],
                                         action['replace']['from'].format(**variables),
                                         action['replace']['to'].format(**variables))


@register(name="markdown")
def __bundle_markdown__(action, variables):
    logging.debug('Markdown %s', action)
    conv = Markdown2HTML()
    filepath_in = action['source'].format(**variables)
    filepath_out = action['target'].format(**variables)
    md = open(filepath_in).read()
    converted_md = conv.md2html(md)
    with open(filepath_out, 'w') as fd:
        converted_md.seek(0)
        shutil.copyfileobj(converted_md, fd, -1)


@register(name="graph")
def __bundle_graph__(action, variables):
    logging.debug('Graph %s', action)
    documentation = action['target'].format(**variables)
    version = action['version'].format(**variables)
    title = action['title'].format(**variables)
    if not isdir(documentation):
        os.mkdir(documentation)
    compact = action['compact'] if 'compact' in action else False
    og = OntoGraf([f['inputFile'] for f in __bundle_file_list(action, variables)],
                  outpath=documentation, wee=compact, title=title, version=version)
    og.gather_schema_info_from_files()
    og.create_schema_graf()


def __bundle_local_sparql__(action, variables, output, queries):
    g = __build_graph_from_inputs__(action, variables)
    updated = False
    for query_file, query_text in queries:
        parsed_update = None
        parsed_query = None
        try:
            parsed_update = __parse_update_query__(query_text)
        except ParseException:
            # Not a update
            parsed_query = prepareQuery(query_text)

        if parsed_update:
            g.update(parsed_update)
            __transfer_query_prefixes__(g, parsed_update)
            updated = True
        else:
            results = g.query(
                parsed_query,
                initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

            if results.vars is not None:
                # SELECT Query
                select_output = __determine_output_file_name__(output, queries, query_file, suffix='csv')
                with open(select_output, 'w') as csv_file:
                    __serialize_select_results__(csv_file, results)

            elif results.graph is not None:
                # CONSTRUCT Query
                __transfer_query_prefixes__(results.graph, parsed_query)
                rdf_format, suffix = __determine_format_and_suffix(action)
                construct_output = __determine_output_file_name__(output, queries, query_file, suffix=suffix)
                results.graph.serialize(destination=construct_output, format=rdf_format, encoding='utf-8')
            else:
                raise Exception('Unknown query type: ' + query_text)

    if updated:
        if 'format' in action:
            rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
        else:
            rdf_format = 'turtle'
        g.serialize(destination=output, format=rdf_format, encoding='utf-8')


def __transfer_query_prefixes__(g, parsed_update):
    for prefix, uri in parsed_update.prologue.namespace_manager.namespaces():
        g.bind(prefix, uri)


def __determine_format_and_suffix(action: dict) -> tuple:
    if 'format' in action:
        rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
    else:
        rdf_format = 'turtle'
    suffix = 'ttl' if 'format' not in action or action['format'] == 'turtle' else action['format']
    return rdf_format, suffix


def __determine_output_file_name__(output, queries, query_file, suffix):
    if len(queries) == 1:
        select_output = output
    else:
        base, _ = splitext(basename(query_file))
        select_output = os.path.join(output, f'{base}.{suffix}')
    return select_output


def __bundle_endpoint_sparql__(action, variables, output, queries):
    for query_file, query_text in queries:
        parsed_update = None
        parsed_query = None
        try:
            parsed_update = __parse_update_query__(query_text)
        except ParseException:
            # Not a update
            parsed_query = prepareQuery(query_text)

        # parsed_query.algebra.name will be SelectQuery, ConstructQuery or AskQuery
        if parsed_update:
            __endpoint_update_query__(action['endpoint'], query_text)
        else:
            if parsed_query.algebra.name == 'SelectQuery':
                select_output = __determine_output_file_name__(output, queries, query_file, suffix='csv')
                with open(select_output, 'wb') as csv_file:
                    csv_file.write(__endpoint_select_query__(action['endpoint'], query_text))
            elif parsed_query.algebra.name == 'ConstructQuery':
                results = __endpoint_construct_query__(action['endpoint'], query_text)
                rdf_format, suffix = __determine_format_and_suffix(action)
                __transfer_query_prefixes__(results, parsed_query)
                construct_output = __determine_output_file_name__(output, queries, query_file, suffix=suffix)
                results.serialize(destination=construct_output, format=rdf_format, encoding='utf-8')
            else:
                raise Exception('Unknown query type: ' + query_text)


@register(name="sparql")
def __bundle_sparql__(action, variables):
    logging.debug('SPARQL %s', action)
    output = action['target'].format(**variables) if 'target' in action else None
    queries = __build_query_list__(action, variables)

    if 'endpoint' in action:
        __bundle_endpoint_sparql__(action, variables, output, queries)
    else:
        __bundle_local_sparql__(action, variables, output, queries)


def __serialize_select_results__(output, results):
    writer = csv.writer(output)
    writer.writerow(results.vars)
    writer.writerows(results)


def __build_graph_from_inputs__(action, variables):
    """Read RDF files specified by source/[inputs] into a Graph"""
    g = Graph()
    for in_out in __bundle_file_list(action, variables, ignore_target=True):
        onto_file = in_out['inputFile']
        parse_rdf(g, onto_file)
    logging.debug("Input graph size is %d", len(g))
    return g


@register(name="verify")
def __bundle_verify__(action, variables):
    logging.debug('Verify %s', action)
    if action['type'] == 'select':
        __verify_select__(action, variables)
    elif action['type'] == 'ask':
        __verify_ask__(action, variables)
    elif action['type'] == 'construct':
        __verify_construct__(action, variables)
    elif action['type'] == 'shacl':
        __verify_shacl__(action, variables)


def __verify_select__(action, variables):
    queries = __build_query_list__(action, variables)

    g = __build_graph_from_inputs__(action, variables)

    fail_count = 0
    stop_on_fail = __boolean_option__(action, 'stopOnFail', variables, default=True)
    for query_text in queries:
        logging.debug("Executing SELECT query %s", query_text[0])
        parsed_query = prepareQuery(query_text[1])
        results = g.query(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if results.vars is not None:
            output = [results.vars]
            output.extend(results)
            if (len(output)) > 1:
                fail_count += 1
                serialized = io.StringIO()
                __serialize_select_results__(serialized, results)
                if 'target' in action:
                    if not stop_on_fail:
                        # Treat 'target' as directory.
                        target_dir = action['target'].format(**variables)
                        if not isdir(target_dir):
                            os.mkdir(target_dir)
                        base, _ = splitext(basename(query_text[0]))
                        with open(join(target_dir, base + '.csv'), 'w') as select_output:
                            select_output.write(serialized.getvalue())
                    else:
                        with open(action['target'].format(**variables), 'w') as select_output:
                            select_output.write(serialized.getvalue())
                logging.error("Verification query %s produced non-empty results:\n%s",
                              query_text[0], serialized.getvalue())
                if stop_on_fail:
                    break
        else:
            raise Exception('Invalid query for SELECT verify: ' + query_text[1] + ', vars is ' + str(results.vars))

    if fail_count > 0:
        exit(1)


def __endpoint_construct_query__(endpoint: dict, query_text: str) -> Graph:
    sparql = create_endpoint(endpoint['query_uri'], endpoint.get('user'), endpoint.get('password'))

    sparql.setQuery(query_text)
    sparql.setReturnFormat(TURTLE)
    results = sparql.query().convert()
    rg = Graph()
    rg.parse(data=results.decode("utf-8"), format="turtle")
    return rg


def __endpoint_select_query__(endpoint: dict, query_text: str) -> bytes:
    sparql = create_endpoint(endpoint['query_uri'], endpoint.get('user'), endpoint.get('password'))

    results = select_query_csv(sparql, query_text)
    return results


def __endpoint_update_query__(endpoint: dict, query_text: str):
    uri = endpoint.get('update_uri', endpoint['query_uri'])
    sparql = create_endpoint(uri, endpoint.get('user'), endpoint.get('password'))

    sparql.setQuery(query_text)
    return sparql.query()


def __verify_construct__(action, variables):
    queries = __build_query_list__(action, variables)

    g = None
    if 'endpoint' not in action:
        g = __build_graph_from_inputs__(action, variables)

    fail_count = 0
    stop_on_fail = __boolean_option__(action, 'stopOnFail', variables, default=True)
    fail_on_warning = 'failOn' in action and action['failOn'] == 'warning'
    for query_file, query_text in queries:
        logging.debug("Executing CONSTRUCT query %s", query_file)
        parsed_query = prepareQuery(query_text)
        if 'endpoint' in action:
            results = __endpoint_construct_query__(action['endpoint'], query_text)
        else:
            qr = g.query(
                parsed_query,
                initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})
            results = qr.graph

        if results is not None and isinstance(results, Graph):
            if not len(results):
                continue

            for pref, ns in parsed_query.prologue.namespace_manager.namespaces():
                results.bind(pref, ns)
            violation = __process_construct_validation__(output=action.get('target'),
                                                         fail_on_warning=fail_on_warning,
                                                         stop_on_fail=stop_on_fail,
                                                         query_file=query_file,
                                                         graph=results,
                                                         variables=variables)
            if fail_on_warning or violation:
                fail_count += 1
                if stop_on_fail:
                    break
        else:
            raise Exception(f'Invalid query for CONSTRUCT verify: {query_text}')

    if fail_count > 0:
        exit(1)


def __process_construct_validation__(output, fail_on_warning, stop_on_fail, query_file, graph, variables):
    graph.bind("skos", SKOS)
    graph.bind("sh", Namespace('http://www.w3.org/ns/shacl#'))
    serialized, count, violation = __format_validation_results__(graph)
    if not count:
        logging.warning("CONSTRUCT verification %s did not produce well-formed ViolationReport",
                        query_file)
    else:
        if violation or fail_on_warning:
            logging.error("Verification query %s produced non-empty results:\n%s",
                          query_file, serialized)
        else:
            logging.warning("Verification query %s produced non-empty results:\n%s",
                            query_file, serialized)
    if output:
        if not stop_on_fail:
            # Treat 'target' as directory.
            target_dir = output.format(**variables)
            if not isdir(target_dir):
                os.mkdir(target_dir)
            base, _ = splitext(basename(query_file))
            construct_output = join(target_dir, base + '.ttl')
        else:
            construct_output = output.format(**variables)
        graph.serialize(construct_output, format='turtle', encoding='utf-8')
    return violation


def __verify_shacl__(action, variables):
    data_graph = __build_graph_from_inputs__(action, variables)
    shape_graph = __build_graph_from_inputs__(action['shapes'], variables)

    logging.debug("Data graph has %s triples", sum(1 for _ in data_graph))
    logging.debug("Shape graph has %s triples", sum(1 for _ in shape_graph))

    conforms, results_graph, _ = \
        pyshacl.validate(
            data_graph, shacl_graph=shape_graph,
            inference=None if 'inference' not in action else action['inference'],
            abort_on_error=False, meta_shacl=False,
            advanced=True, js=False, debug=False)

    logging.debug("Post-inference data graph has %s triples", sum(1 for _ in data_graph))

    if not conforms:
        if 'target' in action:
            results_graph.serialize(
                destination=action['target'].format(**variables),
                format='turtle', encoding='utf-8')
        result_table, count, violation = __format_validation_results__(results_graph)
        fail_on_warning = 'failOn' in action and action['failOn'] == 'warning'
        if not count:
            logging.warning("SHACL verification did not produce a well-formed ViolationReport:\n%s", result_table)
        else:
            if violation or fail_on_warning:
                logging.error("SHACL verification produced non-empty results:\n%s", result_table)
            else:
                logging.warning("SHACL verification produced non-empty results:\n%s", result_table)
        if fail_on_warning or violation:
            exit(1)


def __format_validation_results__(results_graph: Graph) -> Tuple[str, int, bool]:
    """Format validation results as text table.

    Adjusts the width of the table so that every row fits
    """
    result_table = io.StringIO()
    violations = results_graph.query("""
            prefix sh: <http://www.w3.org/ns/shacl#>
            SELECT ?focus ?path ?value ?component ?severity ?message WHERE {
                ?violation
                   sh:focusNode ?focus ;
                   sh:resultMessage ?message ;
                   sh:resultSeverity ?severity .
                OPTIONAL { ?violation sh:value ?value }
                OPTIONAL { ?violation sh:resultPath ?path }
                OPTIONAL { ?violation sh:sourceConstraintComponent ?component }
            }
        """)
    rows = []
    headers = ['Focus', 'Path', 'Value', 'Severity', 'Message']
    max_length = [len(h) for h in headers]

    def format_value(v):
        return '' if v is None else str(v) if isinstance(v, Literal) else v.n3(results_graph.namespace_manager)

    violation_seen = False
    for row in violations:
        message = str(row.message)
        if len(message) > 50:
            message = message[0:47] + '...'
        severity = row.severity.n3(results_graph.namespace_manager)
        violation_seen |= severity == 'sh:Violation'
        as_text = [
            row.focus.n3(results_graph.namespace_manager),
            format_value(row.path if row.path else row.component),
            format_value(row.value),
            severity,
            message
        ]
        # Extend the width of each column to contain the longest value.
        max_length = [max(a, b) for a, b in zip(max_length, [len(s) for s in as_text])]
        rows.append(as_text)
    row_format = " ".join(f"{{:{length}.{length}}}" for length in max_length) + "\n"
    rows.sort(key=lambda x: x[0])
    result_table.write(row_format.format(*headers))
    for row in rows:
        result_table.write(row_format.format(*row))
    return result_table.getvalue(), len(rows), violation_seen


def __verify_ask__(action, variables):
    queries = __build_query_list__(action, variables)

    g = __build_graph_from_inputs__(action, variables)

    fail_count = 0
    stop_on_fail = __boolean_option__(action, 'stopOnFail', variables, default=True)
    for query_text in queries:
        parsed_query = prepareQuery(query_text[1])
        results = g.query(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if results.askAnswer is not None:
            if results.askAnswer != action['expected']:
                fail_count += 1
                logging.error(
                    "Verification ASK query %s did not match expected result %s",
                    query_text[0], action['expected'])
                if stop_on_fail:
                    break
        else:
            raise Exception(f'Invalid query for ASK verify: {query_text}')

    if fail_count > 0:
        exit(1)


def __build_query_list__(action: dict, variables: dict) -> List[Tuple]:
    """Expands the query specification into list of (file name, query text) tuples."""
    if 'query' in action:
        query = action['query'].format(**variables)
        if isfile(query):
            queries = [(query, open(query, 'r').read())]
        else:
            queries = [('inline', query)]
    elif 'queries' in action:
        query_files = [
            entry['inputFile'] for entry in
            __bundle_file_list(action['queries'], variables, ignore_target=True)]
        queries = [(query, open(query, 'r').read()) for query in query_files]
    else:
        raise Exception('No queries specified for verify action: ' + str(action))
    return queries


def __boolean_option__(action, key, variables, default=False):
    if key not in action:
        return default
    value = action[key]
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value.format(**variables)).lower() in ("yes", "true", "t", "1")


@register(name="export")
def __bundle_export__(action, variables):
    logging.debug('Export %s', action)
    if __boolean_option__(action, 'compress', variables):
        output = gzip.open(action['target'].format(**variables), 'wt', encoding="utf-8")
    else:
        output = open(action['target'].format(**variables), 'w', encoding="utf-8")

    o_format = action['format'].format(**variables) if 'format' in action else 'turtle'
    o_format = 'pretty-xml' if o_format == 'xml' else o_format

    context = action['context'].format(**variables) if 'context' in action else None

    merge = None
    if 'merge' in action:
        merge = (action['merge']['iri'], action['merge']['version'])

    paths = list(f['inputFile']
                 for f in __bundle_file_list(action, variables, ignore_target=True))

    defined_by = None
    if 'definedBy' in action:
        defined_by = action['definedBy'].format(**variables)

    __perform_export__(output, o_format,
                       paths,
                       context,
                       __boolean_option__(action, 'stripVersions', variables),
                       merge,
                       defined_by,
                       __boolean_option__(action, 'retainDefinedBy', variables),
                       __boolean_option__(action, 'versionedDefinedBy', variables))

    output.close()


def bundle_ontology(command_line_variables, bundle_path):
    """
    Bundle ontology and related artifacts for release.

    Parameters
    ----------
    command_line_variables : list
        list of variable values to substitute into the template.
    bundle_path : string
        Path to YAML or JSON bundle definition.

    Returns
    -------
    None.

    """
    extension = os.path.splitext(bundle_path)[1]
    schema_file = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        'bundle_schema.yaml')
    with open(bundle_path, 'r') as b_stream, open(schema_file, 'r') as schema:
        if extension == '.yaml':
            bundle = yaml.safe_load(b_stream)
        else:
            # assume json regardless of extension
            bundle = json.load(b_stream)

        # will throw ValidationError on failure
        validate(bundle, yaml.safe_load(schema))

    variables = VarDict()
    variables.update(bundle['variables'])
    variables.update(dict((n, v) for n, v in command_line_variables))
    substituted = dict((k, variables[k]) for k in variables)

    for action in bundle['actions']:
        if 'message' in action:
            logging.info(action['message'].format(**substituted))
        if action['action'] == 'transform':
            __bundle_transform__(action, bundle['tools'], substituted)
        elif action['action'] == 'mkdir':
            path = action['directory'].format(**substituted)
            if not isdir(path):
                os.mkdir(path)
        elif action['action'] in BUNDLE_ACTIONS:
            BUNDLE_ACTIONS[action['action']](action, substituted)
        else:
            raise Exception('Unknown action ' + str(action))


def export_ontology(args, output_format):
    """Export one or more files as a single output.

    Optionally, strips dependency versions and merges ontologies into
    a single new ontology.
    """
    context = args.context if 'context' in args and args.context else None
    defined_by = args.defined_by if 'defined_by' in args and args.defined_by else None

    __perform_export__(args.output, output_format, args.ontology,
                       context,
                       'strip_versions' in args and args.strip_versions,
                       args.merge if 'merge' in args and args.merge else None,
                       defined_by,
                       args.retain_definedBy,
                       args.versioned_definedBy)


def update_ontology(args, output_format):
    """Maintenance updates for ontology files."""
    for onto_file in [file for ref in args.ontology for file in expand_file_ref(ref)]:
        g = Graph()
        orig_format = guess_format(onto_file)
        parse_rdf(g, onto_file, orig_format)
        logging.debug(f'{onto_file} has {len(g)} triples')

        # locate ontology
        ontology = find_single_ontology(g, onto_file)
        if not ontology:
            logging.warning(f'Ignoring {onto_file}, no ontology found')
            continue

        ontology_iri = ontology

        # Set version
        if 'set_version' in args and args.set_version:
            set_version(g, ontology, ontology_iri, args.set_version)
        if 'version_info' in args and args.version_info:
            try:
                set_version_info(g, ontology, args.version_info)
            except Exception as e:
                logging.error(e)
                continue

        # Add rdfs:isDefinedBy
        if 'defined_by' in args and args.defined_by:
            add_defined_by(g, ontology_iri, mode=args.defined_by,
                           replace=not args.retain_definedBy,
                           versioned=args.versioned_definedBy)

        # Update dep versions
        if 'dependency_version' in args and args.dependency_version:
            update_dependency_versions(g, ontology, args.dependency_version)

        # Remove dep versions
        if 'strip_versions' in args and args.strip_versions:
            strip_versions(g, ontology)

        output_updated_ontology(args, g, onto_file, orig_format, output_format)


def output_updated_ontology(args, g, onto_file, orig_format, output_format):
    # Output
    if args.in_place:
        adjusted_format = 'pretty-xml' if orig_format == 'xml' else orig_format
        g.serialize(destination=onto_file,
                    format=adjusted_format,
                    encoding='utf-8')
    else:
        serialized = g.serialize(format=output_format)
        args.output.write(serialized.decode(args.output.encoding))


def main(arguments):
    """Do the thing."""
    args = configure_arg_parser().parse_args(args=arguments)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.command == 'bundle':
        bundle_ontology(args.variables, args.bundle)
        return

    if args.command == 'graphic':
        generate_graphic(args.action, args.ontology, args.endpoint,
                         limit=args.instance_limit, threshold=args.predicate_threshold,
                         single_graph=args.single_ontology_graphs,
                         wee=args.wee, outpath=args.output, version=args.version,
                         no_image=args.no_image, title=args.title,
                         include=args.include, exclude=args.exclude,
                         include_pattern=args.include_pattern,
                         exclude_pattern=args.exclude_pattern,
                         show_shacl=args.show_shacl)
        return

    of = 'pretty-xml' if args.format == 'xml' else args.format

    if args.command == 'export':
        export_ontology(args, of)
    else:
        update_ontology(args, of)


def run_tool():
    """Entry point for executable script."""
    main(sys.argv[1:] if len(sys.argv) > 1 else ['-h'])
