"""Toolkit for ontology maintenance and release."""
import io
import logging
import argparse
import os
import sys
from os.path import join, isdir, isfile, basename, splitext
from glob import glob
from urllib.parse import urlparse
import re
import subprocess
import shutil
import gzip
import json
import yaml
import csv
from jsonschema import validate
from rdflib import Graph, ConjunctiveGraph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
from rdflib.util import guess_format
from rdflib.plugins.sparql import prepareQuery
import pyshacl
from .ontograph import OntoGraf
from .mdutils import md2html

# f-strings are fine in log messages
# pylint: disable=W1202
# CamelCase variable names are fine
# pylint: disable=C0103


def _uri_validator(x):
    """Check for valid URI."""
    try:
        result = urlparse(x)
        return all([result.scheme, any([result.netloc, result.path])])
    except ValueError:
        return False


class UriValidator(argparse.Action):
    """Validates IRI argument."""

    # No public method needed
    # pylint: disable=R0903
    def __call__(self, parser, namespace, values, option_string=None):
        """First argument is a valid URI, 2nd a valid semantic version."""
        iri = None
        if _uri_validator(values):
            iri = URIRef(values)
        else:
            parser.error(f'Invalid URI {values}')
        setattr(namespace, self.dest, iri)


class OntologyUriValidator(argparse.Action):
    """Validates ontology IRI and version arguments."""

    # No public method needed
    # pylint: disable=R0903
    def __call__(self, parser, namespace, values, option_string=None):
        """First argument is a valid URI, 2nd a valid semantic version."""
        iri = None
        if _uri_validator(values[0]):
            iri = URIRef(values[0])
        else:
            parser.error(f'Invalid merge ontology URI {values[0]}')
        if not re.match(r'\d+(\.\d+){0,2}', values[1]):
            parser.error(f'Invalid merge ontology version {values[1]}')
        setattr(namespace, self.dest, [iri, values[1]])


def configure_arg_parser():
    """Configure command line parser."""
    parser = argparse.ArgumentParser(description='Ontology toolkit.')
    subparsers = parser.add_subparsers(help='sub-command help', dest='command')

    update_parser = subparsers.add_parser('update',
                                          help='Update versions and dependencies')

    output_format_group = update_parser.add_mutually_exclusive_group()
    output_format_group.add_argument(
        '-f', '--format', action='store',
        default='turtle', choices=['xml', 'turtle', 'nt'],
        help='Output format')
    output_format_group.add_argument(
        '-i', '--in-place', action="store_true",
        help="Overwrite each input file with update, preserving format")

    update_parser.add_argument('-o', '--output',
                               type=argparse.FileType('w', encoding='utf-8'),
                               default=sys.stdout,
                               help='Path to output file. Will be ignored if '
                               '--in-place is specified.')
    update_parser.add_argument('-b', '--defined-by', action="store",
                               nargs="?", const='strict',
                               choices=['all', 'strict'],
                               help='Add rdfs:isDefinedBy to every resource defined. '
                               'If the (default) "strict" argument is provided, only '
                               'owl:Class, owl:ObjectProperty, owl:DatatypeProperty, '
                               'owl:AnnotationProperty and owl:Thing entities will be '
                               'annotated. If "all" is provided, every entity that has '
                               'any properties other than rdf:type will be annotated. '
                               'Will override any existing rdfs:isDefinedBy annotations '
                               'on the affected entities unless --retain-definedBy is '
                               'specified.')
    update_parser.add_argument('--retain-definedBy', action="store_true",
                               help='Retain existing values of rdfs:isDefinedBy')
    update_parser.add_argument('--versioned-definedBy', action="store_true",
                               help='Use versionIRI for rdfs:isDefinedBy, when available')
    update_parser.add_argument('-v', '--set-version', action="store",
                               help='Set the version of the defined ontology')
    update_parser.add_argument('--version-info', action="store",
                               nargs='?', const='auto',
                               help='Adjust versionInfo, defaults to "Version X.x.x"')
    update_parser.add_argument('-d', '--dependency-version', action="append",
                               metavar=('DEPENDENCY', 'VERSION'),
                               nargs=2, default=[],
                               help='Update the import of DEPENDENCY to VERSION')
    update_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file or directory containing OWL files")

    export_parser = subparsers.add_parser('export', help='Export ontology')

    format_parser = export_parser.add_mutually_exclusive_group()
    format_parser.add_argument('-f', '--format', action='store',
                               default='turtle',
                               choices=['xml', 'turtle', 'nt'],
                               help='Output format')
    format_parser.add_argument('-c', '--context', action=UriValidator,
                               help='Export as N-Quads in CONTEXT.')

    export_parser.add_argument('-o', '--output',
                               type=argparse.FileType('w', encoding='utf-8'),
                               default=sys.stdout,
                               help='Path to output file.')
    export_parser.add_argument('-s', '--strip-versions', action="store_true",
                               help='Remove versions from imports.')
    export_parser.add_argument('-m', '--merge', action=OntologyUriValidator, nargs=2,
                               metavar=('IRI', 'VERSION'),
                               help='Merge all inputs into a single ontology'
                               ' with the given IRI and version')
    export_parser.add_argument('-b', '--defined-by', action="store",
                               nargs="?", const='strict',
                               choices=['all', 'strict'],
                               help='Add rdfs:isDefinedBy to every resource defined. '
                               'If the (default) "strict" argument is provided, only '
                               'owl:Class, owl:ObjectProperty, owl:DatatypeProperty, '
                               'owl:AnnotationProperty and owl:Thing entities will be '
                               'annotated. If "all" is provided, every entity that has '
                               'any properties other than rdf:type will be annotated.')
    export_parser.add_argument('--retain-definedBy', action="store_true",
                               help='When merging ontologies, retain existing values '
                               'of rdfs:isDefinedBy')
    export_parser.add_argument('--versioned-definedBy', action="store_true",
                               help='Use versionIRI for rdfs:isDefinedBy, when available')
    export_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file or directory containing OWL files")

    bundle_parser = subparsers.add_parser('bundle', help='Bundle ontology for release')
    bundle_parser.add_argument('-v', '--variable', action="append",
                               dest='variables',
                               metavar=('VARIABLE', 'VALUE'),
                               nargs=2, default=[],
                               help='Set value of VARIABLE to VALUE')
    bundle_parser.add_argument('bundle', default='bundle.json',
                               help="JSON or YAML bundle definition")

    graphic_parser = subparsers.add_parser('graphic',
                                           help='Create PNG graphic and dot'
                                           ' file from OWL files')
    graphic_parser.add_argument('-o', '--output', action="store",
                                default=os.getcwd(),
                                help="Output directory for generated graphics")
    graphic_parser.add_argument('-v', '--version', help="Version to place in graphic",
                                action="store")
    graphic_parser.add_argument('-w', '--wee', action="store_true",
                                help="a version of the graphic with only core"
                                " information about ontology and imports")
    graphic_parser.add_argument('ontology', nargs="*", default=[],
                                help="Ontology file, directory or name pattern")
    return parser


def findSingleOntology(g, onto_file):
    """Verify that file has a single ontology defined and return the IRI."""
    ontologies = list(g.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) == 0:
        logging.warning(f'No ontology definition found in {onto_file}')
        return None
    if len(ontologies) > 1:
        logging.error(f'Multiple ontologies defined in {onto_file}, skipping')
        return None

    ontology = ontologies[0]
    logging.info(f'{ontology} found in {onto_file}')
    return ontology


def set_version(g, ontology, ontology_iri, version):
    """Add or replace versionIRI for the specified ontology."""
    old_version = next(g.objects(ontology, OWL.versionIRI), None)
    if old_version:
        logging.debug(f'Removing versionIRI {old_version} from {ontology}')
        g.remove((ontology, OWL.versionIRI, old_version))

    version_iri = URIRef(f"{ontology_iri}{version}")
    g.add((ontology, OWL.versionIRI, version_iri))
    logging.debug(f'versionIRI {version_iri} added for {ontology}')


def set_version_info(g, ontology, version_info):
    """Add versionInfo for the ontology.

    If versionInfo is not provided, extracts ontology version from versionIRI.
    """
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
    logging.debug(f'versionInfo "{version_info}" added for {ontology}')


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


def updateDependencyVersions(g, ontology, versions):
    """Update ontology dependency versions.

    The versions dict maps ontology IRI to their versions.
    Inspect the imports of the current ontology, and if they match
    (ignoring version) any of the ontology provided in the argument,
    update them to the new version.
    """
    # Gather current dependencies
    currentDeps = g.objects(ontology, OWL.imports)
    for dv in versions:
        dep, ver = dv
        pattern = re.compile(f'{dep}(\\d+\\.\\d+\\.\\d+)?')
        match = next((c for c in currentDeps if pattern.search(str(c))), None)
        if match:
            # Updating current dependency
            current = pattern.search(str(match)).group(1)
            if current:
                logging.debug(f'Removing dependency {current} for {dep}')
                newVersionURI = URIRef(str(match).replace(current, ver))
            else:
                logging.debug(f'Removing unversioned depenendency for {dep}')
                newVersionURI = URIRef(f'{str(match)}{ver}')
            g.remove((ontology, OWL.imports, match))

            g.add((ontology, OWL.imports, newVersionURI))
            logging.info(f'Updated dependency to {newVersionURI}')
        else:
            # New versioned dependency, assuming full URI
            newVersionURI = URIRef(f'{dep}{ver}')
            g.add((ontology, OWL.imports, newVersionURI))
            logging.info(f'Added dependency for {newVersionURI}')


def stripVersions(g, ontology=None):
    """Remove versions (numeric or X.x.x placeholder) from imports."""
    # Gather current dependencies
    ontologies = [ontology] if ontology else list(g.subjects(RDF.type, OWL.Ontology))
    for o in ontologies:
        currentDeps = g.objects(o, OWL.imports)
        pattern = re.compile('^(.*?)((\\d+|[Xx])\\.(\\d+|[Xx])\\.(\\d+|[Xx]))?$')
        for d in currentDeps:
            match = pattern.match(str(d))
            if match.group(2):
                logging.debug(f'Removing version for {d}')
                g.remove((o, OWL.imports, d))
                g.add((o, OWL.imports, URIRef(match.group(1))))


def versionSensitiveMatch(reference, ontologies, versions):
    """Check if reference is in ontologies, ignoring version."""
    match = re.match(r'^(.*?)((\d+|[Xx])\.(\d+|[Xx])\.(\d+|[Xx]))?$',
                     str(reference))
    refWithoutVersion = match.group(1)
    return URIRef(refWithoutVersion) in ontologies or reference in versions


def cleanMergeArtifacts(g, iri, version):
    """Remove all existing ontology declaration, replace with new merged ontology."""
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    versions = set(v for o in ontologies for v in g.objects(o, OWL.versionIRI))
    externalImports = list(
        i for i in g.objects(subject=None, predicate=OWL.imports)
        if not versionSensitiveMatch(i, ontologies, versions))
    for o in ontologies:
        logging.debug(f'Removing existing ontology {o}')
        for t in list(g.triples((o, None, None))):
            g.remove(t)
    logging.debug(f'Creating new ontology {iri}:{version}')
    g.add((iri, RDF.type, OWL.Ontology))
    g.add((iri, OWL.versionIRI, URIRef(str(iri) + version)))
    g.add((iri, OWL.versionInfo, Literal("Created by merge tool.", datatype=XSD.string)))
    for i in externalImports:
        logging.debug(f'Transferring external dependency {i} to {iri}')
        g.add((iri, OWL.imports, i))


def expandFileRef(path):
    """Expand file reference to a list of paths.

    If a file is provided, return as is. If a directory, return all .owl
    files in the directory, outherwise interpret path as a glob pattern.
    """
    if isfile(path):
        return [path]
    if isdir(path):
        return glob(join(path, '*.owl'))
    return glob(path)


def serializeToOutputDir(tools, output, version, file):
    """Serialize ontology file using standard options."""
    base, ext = splitext(basename(file))
    outputFile = join(output, f"{base}{version}{ext}")
    logging.debug(f"Serializing {file} to {output}")
    serializeArgs = [
        "java",
        "-jar", join(tools, "rdf-toolkit.jar"),
        "-tfmt", "rdf-xml",
        "-sdt", "explicit",
        "-dtd",
        "-ibn",
        "-s", file,
        "-t", outputFile]
    subprocess.run(serializeArgs)
    return outputFile


def replacePatternInFile(file, from_pattern, to_string):
    """Replace regex pattern in file contents."""
    with open(file, 'r') as f:
        replaced = re.compile(from_pattern).sub(to_string, f.read())
    with open(file, 'w') as f:
        f.write(replaced)


def copyIfPresent(fromLoc, toLoc):
    """Copy file to new location if present."""
    if isfile(fromLoc):
        shutil.copy(fromLoc, toLoc)


def generateGraphic(fileRefs, compact, output, version):
    """
    Generate ontology .dot and .png graphic.

    Parameters
    ----------
    fileRefs : list(string)
        List of paths or glob patterns from which to gather ontologies.
    compact : boolean
        If True, generate a compact ontology graph.
    output : string
        Path of directory where graph will be output.
    version : string
        Version to be used in graphic title.

    Returns
    -------
    None.

    """
    allFiles = [file for ref in fileRefs for file in expandFileRef(ref)]
    og = OntoGraf(allFiles, outpath=output, wee=compact, version=version)
    og.gather_info()
    og.create_graf()


def __perform_export__(output, output_format, paths, context=None,
                       strip_versions=False,
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

    for onto_file in [file for ref in paths for file in expandFileRef(ref)]:
        parse_graph.parse(onto_file, format=guess_format(onto_file))

    # Remove dep versions
    if strip_versions:
        stripVersions(parse_graph)

    if merge:
        cleanMergeArtifacts(parse_graph, URIRef(merge[0]), merge[1])

    # Add rdfs:isDefinedBy
    if defined_by:
        ontology_iri = findSingleOntology(parse_graph, 'merged graph')
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
        Containes 'inputFile' and 'outputFile' unless ignore_target
        is specifed.

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
            for input_file in glob(os.path.join(src_dir, pattern)):
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


def __bundle_transform__(action, tools, variables):
    logging.debug('Transform %s', action)
    tool = next((t for t in tools if t['name'] == action['tool']), None)
    if not tool:
        raise Exception('Missing tool ', action['tool'])
    if tool['type'] == 'Java':
        __bundle_transform_java__(action, tool, variables)
    elif tool['type'] == 'sparql':
        __bundle_transform_sparql__(action, tool, variables)
    else:
        raise Exception('Unsupported tool type ', tool['type'])


def __bundle_transform_java__(action, tool, variables):
    for in_out in __bundle_file_list(action, variables):
        invocation_vars = VarDict()
        invocation_vars.update(variables)
        invocation_vars.update(in_out)
        interpreted_args = ["java", "-jar", tool['jar'].format(**invocation_vars)] + [
            arg.format(**invocation_vars) for arg in tool['arguments']]
        logging.debug('Running %s', interpreted_args)
        status = subprocess.run(interpreted_args, capture_output=True)
        if status.returncode != 0:
            logging.error("Tool %s exited with %d: %s", interpreted_args, status.returncode, status.stderr)
            exit(1)
        if 'replace' in action:
            replacePatternInFile(in_out['outputFile'],
                                 action['replace']['from'].format(**invocation_vars),
                                 action['replace']['to'].format(**invocation_vars))


def __bundle_transform_sparql__(action, tool, variables):
    query = tool['query'].format(**variables)
    if isfile(query):
        query_text = open(query, 'r').read()
    else:
        query_text = query

    from rdflib.plugins.sparql.parser import parseUpdate
    from rdflib.plugins.sparql.algebra import translateUpdate

    parsed_query = translateUpdate(parseUpdate(query_text))

    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        g.parse(onto_file, format=rdf_format)

        g.update(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if 'format' in tool:
            rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
        else:
            rdf_format = rdf_format

        g.serialize(destination=in_out['outputFile'], format=rdf_format, encoding='utf-8')

        if 'replace' in action:
            replacePatternInFile(in_out['outputFile'],
                                 action['replace']['from'].format(**variables),
                                 action['replace']['to'].format(**variables))


def __bundle_defined_by__(action, variables):
    logging.debug('Add definedBy %s', action)
    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        g.parse(onto_file, format=rdf_format)

        # locate ontology
        ontology = findSingleOntology(g, onto_file)
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
            replacePatternInFile(in_out['outputFile'],
                                 action['replace']['from'].format(**variables),
                                 action['replace']['to'].format(**variables))


def __bundle_copy__(action, variables):
    logging.debug('Copy %s', action)
    for in_out in __bundle_file_list(action, variables):
        if isfile(in_out['inputFile']):
            shutil.copy(in_out['inputFile'], in_out['outputFile'])
            if 'replace' in action:
                replacePatternInFile(in_out['outputFile'],
                                     action['replace']['from'].format(**variables),
                                     action['replace']['to'].format(**variables))


def __bundle_move__(action, variables):
    logging.debug('Move %s', action)
    for in_out in __bundle_file_list(action, variables):
        if isfile(in_out['inputFile']):
            shutil.move(in_out['inputFile'], in_out['outputFile'])
            if 'replace' in action:
                replacePatternInFile(in_out['outputFile'],
                                     action['replace']['from'].format(**variables),
                                     action['replace']['to'].format(**variables))


def __bundle_markdown__(action, variables):
    logging.debug('Markdown %s', action)
    conv = md2html()
    filepath_in = action['source'].format(**variables)
    filepath_out = action['target'].format(**variables)
    md = open(filepath_in).read()
    converted_md = conv.md2html(md)
    with open(filepath_out, 'w') as fd:
        converted_md.seek(0)
        shutil.copyfileobj(converted_md, fd, -1)


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
    og.gather_info()
    og.create_graf()


def __bundle_sparql__(action, variables):
    logging.debug('SPARQL %s', action)
    output = action['target'].format(**variables)
    query = action['query'].format(**variables)
    if isfile(query):
        query_text = open(query, 'r').read()
    else:
        query_text = query

    g = __build_graph_from_inputs__(action, variables)

    parsed_query = prepareQuery(query_text)
    results = g.query(
        parsed_query,
        initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

    if results.vars is not None:
        # SELECT Query
        with open(output, 'w') as csv_file:
            __serialize_select_results__(csv_file, results)
    elif results.graph is not None:
        # CONSTRUCT Query
        if 'format' in action:
            rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
        else:
            rdf_format = 'turtle'
        for prefix, uri in parsed_query.prologue.namespace_manager.namespaces():
            results.graph.bind(prefix, uri)
        results.graph.serialize(destination=output, format=rdf_format, encoding='utf-8')
    else:
        raise Exception('Unknown query type: ' + query_text)


def __serialize_select_results__(output, results):
    writer = csv.writer(output)
    writer.writerow(results.vars)
    writer.writerows(results)


def __build_graph_from_inputs__(action, variables):
    """Read RDF files specified by source/[inputs] into a Graph"""
    g = Graph()
    for in_out in __bundle_file_list(action, variables, ignore_target=True):
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        g.parse(onto_file, format=rdf_format)
    return g


def __bundle_verify__(action, variables):
    logging.debug('Verify %s', action)
    if action['type'] == 'select':
        __verify_select__(action, variables)
    elif action['type'] == 'ask':
        __verify_ask__(action, variables)
    elif action['type'] == 'shacl':
        __verify_shacl__(action, variables)


def __verify_select__(action, variables):
    queries = __build_query_list__(action, variables)

    g = __build_graph_from_inputs__(action, variables)

    for query_text in queries:
        parsed_query = prepareQuery(query_text[1])
        results = g.query(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if results.vars is not None:
            output = [results.vars]
            output.extend(results)
            if (len(output)) > 1:
                serialized = io.StringIO()
                __serialize_select_results__(serialized, results)
                if 'target' in action:
                    with open(action['target'].format(**variables), 'w') as select_output:
                        select_output.write(serialized.getvalue())
                logging.error("Verification query %s produced non-empty results:\n%s",
                              query_text[0], serialized.getvalue())
                exit(1)
        else:
            raise Exception('Invalid query for SELECT verify: ' + query_text)


def __verify_shacl__(action, variables):
    data_graph = __build_graph_from_inputs__(action, variables)
    shape_graph = __build_graph_from_inputs__(action['shapes'], variables)

    logging.debug("Data graph has %s triples", sum(1 for triple in data_graph))
    logging.debug("Shape graph has %s triples", sum(1 for triple in shape_graph))

    conforms, results_graph, results_text = \
        pyshacl.validate(
            data_graph, shacl_graph=shape_graph,
            inference=None if 'inference' not in action else action['inference'],
            abort_on_error=False, meta_shacl=False,
            advanced=False, js=False, debug=False)

    if not conforms:
        if 'target' in action:
            results_graph.serialize(
                destination=action['target'].format(**variables),
                format='turtle', encoding='utf-8')
        logging.error("SHACL verification produced non-empty results:\n%s", results_text)
        exit(1)


def __verify_ask__(action, variables):
    queries = __build_query_list__(action, variables)

    g = __build_graph_from_inputs__(action, variables)

    for query_text in queries:
        parsed_query = prepareQuery(query_text[1])
        results = g.query(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if results.askAnswer is not None:
            if results.askAnswer != action['expected']:
                logging.error(
                    "Verification ASK query %s did not match expected result %s",
                    query_text[0], action['expected'])
                exit(1)
        else:
            raise Exception('Invalid query for ASK verify: ' + query_text)


def __build_query_list__(action, variables):
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


def __boolean_option__(action, key, variables):
    if key not in action:
        return False
    value = action[key]
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value.format(**variables)).lower() in ("yes", "true", "t", "1")


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


def bundleOntology(command_line_variables, bundle_path):
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
        if action['action'] == 'transform':
            __bundle_transform__(action, bundle['tools'], substituted)
        elif action['action'] == 'mkdir':
            path = action['directory'].format(**substituted)
            if not isdir(path):
                os.mkdir(path)
        elif action['action'] == 'copy':
            __bundle_copy__(action, substituted)
        elif action['action'] == 'move':
            __bundle_move__(action, substituted)
        elif action['action'] == 'markdown':
            __bundle_markdown__(action, substituted)
        elif action['action'] == 'graph':
            __bundle_graph__(action, substituted)
        elif action['action'] == 'definedBy':
            __bundle_defined_by__(action, substituted)
        elif action['action'] == 'export':
            __bundle_export__(action, substituted)
        elif action['action'] == 'sparql':
            __bundle_sparql__(action, substituted)
        elif action['action'] == 'verify':
            __bundle_verify__(action, substituted)
        else:
            raise Exception('Unknown action ' + str(action))


def exportOntology(args, output_format):
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


def updateOntology(args, output_format):
    """Maintenance updates for ontology files."""
    for onto_file in [file for ref in args.ontology for file in expandFileRef(ref)]:
        g = Graph()
        orig_format = guess_format(onto_file)
        g.parse(onto_file, format=orig_format)
        logging.debug(f'{onto_file} has {len(g)} triples')

        # locate ontology
        ontology = findSingleOntology(g, onto_file)
        if not ontology:
            logging.warning(f'Ignoring {onto_file}, no ontology found')
            continue

        ontology_iri = ontology

        # Set version
        if 'set_version' in args and args.set_version:
            set_version(g, ontology, ontology_iri, args.set_version)
        if 'version_info' in args and args.version_info:
            version_info = args.version_info
            if version_info == 'auto':
                # Not specified, generate automatically
                version_info = None
            try:
                set_version_info(g, ontology, version_info)
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
            updateDependencyVersions(g, ontology, args.dependency_version)

        # Remove dep versions
        if 'strip_versions' in args and args.strip_versions:
            stripVersions(g, ontology)

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
    logging.basicConfig(level=logging.DEBUG)

    args = configure_arg_parser().parse_args(args=arguments)

    if args.command == 'bundle':
        bundleOntology(args.variables, args.bundle)
        return

    if args.command == 'graphic':
        generateGraphic(args.ontology, args.wee, args.output, args.version)
        return

    of = 'pretty-xml' if args.format == 'xml' else args.format

    if args.command == 'export':
        exportOntology(args, of)
    else:
        updateOntology(args, of)


def run_tool():
    """Entry point for executable script."""
    main(sys.argv[1:] if len(sys.argv) > 1 else ['-h'])


if __name__ == '__main__':
    run_tool()
