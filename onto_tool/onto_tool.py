"""Toolkit for ontology maintenance and release."""
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
import json
import yaml
from jsonschema import validate
from rdflib import Graph, ConjunctiveGraph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
from rdflib.util import guess_format
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
        return all([result.scheme, result.netloc, result.path])
    except ValueError:
        return False


class UriValidator(argparse.Action):
    """Validates IRI argument."""

    # No public method needed
    # pylint: disable=R0903
    def __call__(self, parser, namespace, values, option_string=None):
        """First argument is a valid URI, 2nd a valid semantic version."""
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
        if _uri_validator(values[0]):
            iri = URIRef(values[0])
        else:
            parser.error(f'Invalid merge ontology URI {values[0]}')
        if not re.match(r'\d+(\.\d+){0,2}', values[1]):
            parser.error(f'Invalid merge ontology version {values[1]}')
        setattr(namespace, self.dest, [iri, values[1]])


def configureArgParser():
    """Configure command line parser."""
    parser = argparse.ArgumentParser(description='Ontology toolkit.')
    subparsers = parser.add_subparsers(help='sub-command help', dest='command')

    update_parser = subparsers.add_parser('update',
                                          help='Update versions and dependencies')
    update_parser.add_argument('-o', '--output-format', action='store',
                               default='turtle',
                               choices=['xml', 'turtle', 'nt'],
                               help='Output format')
    update_parser.add_argument('-b', '--defined-by', action="store_true",
                               help='Add rdfs:isDefinedBy to every resource defined.')
    update_parser.add_argument('-v', '--set-version', action="store",
                               help='Set the version of the defined ontology')
    update_parser.add_argument('-i', '--version-info', action="store",
                               nargs='?', const='auto',
                               help='Adjust versionInfo, defaults to "Version X.x.x')
    update_parser.add_argument('-d', '--dependency-version', action="append",
                               metavar=('DEPENDENCY', 'VERSION'),
                               nargs=2, default=[],
                               help='Update the import of DEPENDENCY to VERSION')
    update_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file or directory containing OWL files")

    export_parser = subparsers.add_parser('export', help='Export ontology')

    format_parser = export_parser.add_mutually_exclusive_group()
    format_parser.add_argument('-o', '--output-format', action='store',
                               default='turtle',
                               choices=['xml', 'turtle', 'nt'],
                               help='Output format')
    format_parser.add_argument('-c', '--context', action=UriValidator,
                               help='Export as N-Quads in CONTEXT.')

    export_parser.add_argument('-s', '--strip-versions', action="store_true",
                               help='Remove versions from imports.')
    export_parser.add_argument('-m', '--merge', action=OntologyUriValidator, nargs=2,
                               metavar=('IRI', 'VERSION'),
                               help='Merge all inputs into a single ontology'
                               ' with the given IRI and version')
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


def setVersion(g, ontology, ontologyIRI, version):
    """Add or replace versionIRI for the specified ontology."""
    g.add((ontology, OWL.ontologyIRI, ontologyIRI))
    logging.debug(f'ontologyIRI {ontologyIRI} added for {ontology}')

    oldVersion = next(g.objects(ontology, OWL.versionIRI), None)
    if oldVersion:
        logging.debug(f'Removing versionIRI {oldVersion} from {ontology}')
        g.remove((ontology, OWL.versionIRI, oldVersion))

    versionIRI = URIRef(f"{ontologyIRI}{version}")
    g.add((ontology, OWL.versionIRI, versionIRI))
    logging.debug(f'versionIRI {versionIRI} added for {ontology}')


def setVersionInfo(g, ontology, versionInfo):
    """Add versionInfo for the ontology.

    If versionInfo is not provided, extracts ontology version from versionIRI.
    """
    pattern = re.compile('^(.*?)(\\d+\\.\\d+\\.\\d+)?$')
    versionIRI = next(g.objects(ontology, OWL.versionIRI), None)
    version = pattern.match(str(versionIRI)).group(2) if versionIRI else None
    if not version and not versionInfo:
        raise Exception(f'No version found for {ontology}, must specify version info')

    oldVersionInfo = next(g.objects(ontology, OWL.versionInfo), None)
    if oldVersionInfo:
        logging.debug(f'Removing previous versionInfo from {ontology}')
        g.remove((ontology, OWL.versionInfo, oldVersionInfo))

    if not versionInfo:
        versionInfo = "Version " + version
    g.add((ontology, OWL.versionInfo, Literal(versionInfo, datatype=XSD.string)))
    logging.debug(f'versionInfo "{versionInfo}" added for {ontology}')


def addDefinedBy(g, ontologyIRI):
    """Add rdfs:isDefinedBy to every entity declared by the ontology."""
    definitions = g.query(
        """
        SELECT distinct ?defined ?label ?defBy WHERE {
          VALUES ?dtype {
            owl:Class
            owl:ObjectProperty
            owl:DatatypeProperty
            owl:AnnotationProperty
          }
          ?defined a ?dtype ; skos:prefLabel|rdfs:label ?label .
          OPTIONAL { ?defined rdfs:isDefinedBy ?defBy }
        }
        """,
        initNs={'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})
    for d in definitions:
        if d.defBy:
            if d.defBy == ontologyIRI:
                logging.debug(f'{d.defined} already defined by {ontologyIRI}')
            else:
                logging.warning(f'{d.defined} defined by {d.defBy}'
                                f' instead of {ontologyIRI}')
        else:
            logging.debug(f'Added definedBy to {d.defined}')
            g.add((d.defined, RDFS.isDefinedBy, ontologyIRI))


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


def versionSensitiveMatch(reference, ontologies):
    """Check if reference is in ontologies, ignoring version."""
    match = re.match(r'^(.*?)((\d+|[Xx])\.(\d+|[Xx])\.(\d+|[Xx]))?$',
                     str(reference))
    refWithoutVersion = match.group(1)
    return URIRef(refWithoutVersion) in ontologies


def cleanMergeArtifacts(g, iri, version):
    """Remove all existing ontology declaration, replace with new merged ontology."""
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    externalImports = list(
        i for i in g.objects(subject=None, predicate=OWL.imports)
        if not versionSensitiveMatch(i, ontologies))
    for o in ontologies:
        for t in list(g.triples((o, None, None))):
            g.remove(t)
    g.add((iri, RDF.type, OWL.Ontology))
    g.add((iri, OWL.ontologyIRI, iri))
    g.add((iri, OWL.versionIRI, URIRef(str(iri) + version)))
    g.add((iri, OWL.versionInfo, Literal("Created by merge tool.", datatype=XSD.string)))
    for i in externalImports:
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
    og.gatherInfo()
    og.createGraf()


class VarDict(dict):
    """Dict that performs variable substitution on values."""

    def __init__(self, *args):
        """Initialize."""
        dict.__init__(self, args)

    def __getitem__(self, k):
        """Interpret raw value as template to be substituted with variables."""
        template = dict.__getitem__(self, k)
        return template.format(**self)


def __bundle_file_list(action, variables):
    if 'includes' in action:
        # source and target are directories, apply glob
        src_dir = action['source'].format(**variables)
        tgt_dir = action['target'].format(**variables)
        if not isdir(tgt_dir):
            os.mkdir(tgt_dir)
        for pattern in action['includes']:
            for input_file in glob(os.path.join(src_dir, pattern)):
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
                           outputFile=os.path.join(tgt_dir, output_file))
    else:
        yield dict(inputFile=action['source'].format(**variables),
                   outputFile=action['target'].format(**variables))


def __bundle_transform__(action, tools, variables):
    logging.debug('Transform %s', action)
    tool = next((t for t in tools if t['name'] == action['tool']), None)
    if not tool:
        raise Exception('Missing tool ', action['tool'])
    if tool['type'] != 'Java':
        raise Exception('Unsupported tool type ', tool['type'])

    for in_out in __bundle_file_list(action, variables):
        invocation_vars = VarDict()
        invocation_vars.update(variables)
        invocation_vars.update(in_out)
        interpreted_args = ["java", "-jar", tool['jar'].format(**invocation_vars)] + [
            arg.format(**invocation_vars) for arg in tool['arguments']]
        logging.debug('Running %s', interpreted_args)
        subprocess.run(interpreted_args)
        if 'replace' in action:
            replacePatternInFile(in_out['outputFile'],
                                 action['replace']['from'].format(**invocation_vars),
                                 action['replace']['to'].format(**invocation_vars))


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
            ontologyIRI = next(g.objects(ontology, OWL.ontologyIRI), None)
            if ontologyIRI:
                logging.debug(f'{ontologyIRI} found for {ontology}')
            else:
                ontologyIRI = ontology

            addDefinedBy(g, ontologyIRI)

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
    og.gatherInfo()
    og.createGraf()


def bundleOntology(command_line_variables, bundle_path):
    """
    Bundle ontology and related artifacts for release.

    Parameters
    ----------
    variables : list
        list of variable values to substitute into the template.
    bundle : string
        Path to YAML or JSON bundle defintion.

    Returns
    -------
    None.

    """
    extension = os.path.splitext(bundle_path)[1]
    schema_file = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        'bundle_schema.json')
    with open(bundle_path, 'r') as b_stream, open(schema_file, 'r') as schema:
        if extension == '.yaml':
            bundle = yaml.safe_load(b_stream)
        else:
            # assume json regardless of extension
            bundle = json.load(b_stream)

        # will throw ValidationError on failure
        validate(bundle, json.load(schema))

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
        else:
            raise Exception('Unknown action ' + action)


def exportOntology(args, output_format):
    """Export one or more files as a single output.

    Optionally, strips dependency versions and merges ontologies into
    a single new ontology.
    """
    if 'context' in args:
        g = ConjunctiveGraph()
        parse_graph = g.get_context(args.context)
        output_format = 'nquads'
    else:
        g = Graph()
        parse_graph = g

    for onto_file in [file for ref in args.ontology for file in expandFileRef(ref)]:
        parse_graph.parse(onto_file, format=guess_format(onto_file))

    # Remove dep versions
    if 'strip_versions' in args and args.strip_versions:
        stripVersions(parse_graph)

    if 'merge' in args and args.merge:
        cleanMergeArtifacts(parse_graph, URIRef(args.merge[0]), args.merge[1])
    print(g.serialize(format=output_format).decode('utf-8'))


def updateOntology(args, output_format):
    """Maintenance updates for ontology files."""
    for onto_file in [file for ref in args.ontology for file in expandFileRef(ref)]:
        g = Graph()
        g.parse(onto_file, format=guess_format(onto_file))
        logging.debug(f'{onto_file} has {len(g)} triples')

        # locate ontology
        ontology = findSingleOntology(g, onto_file)
        if not ontology:
            logging.warning(f'Ignoring {onto_file}, no ontology found')
            continue

        ontologyIRI = next(g.objects(ontology, OWL.ontologyIRI), None)
        if ontologyIRI:
            logging.debug(f'{ontologyIRI} found for {ontology}')
        else:
            ontologyIRI = ontology

        # Set version
        if 'set_version' in args and args.set_version:
            setVersion(g, ontology, ontologyIRI, args.set_version)
        if 'version_info' in args and args.version_info:
            versionInfo = args.version_info
            if versionInfo == 'auto':
                # Not specified, generate automatically
                versionInfo = None
            try:
                setVersionInfo(g, ontology, versionInfo)
            except Exception as e:
                logging.error(e)
                continue

        # Add rdfs:isDefinedBy
        if 'defined_by' in args and args.defined_by:
            addDefinedBy(g, ontologyIRI)

        # Update dep versions
        if 'dependency_version' in args and args.dependency_version:
            updateDependencyVersions(g, ontology, args.dependency_version)

        # Remove dep versions
        if 'strip_versions' in args and args.strip_versions:
            stripVersions(g, ontology)

        # Output
        print(g.serialize(format=output_format).decode('utf-8'))


def main(arguments):
    """Do the thing."""
    logging.basicConfig(level=logging.DEBUG)

    args = configureArgParser().parse_args(args=arguments)

    if args.command == 'bundle':
        bundleOntology(args.variables, args.bundle)
        return

    if args.command == 'graphic':
        generateGraphic(args.ontology, args.wee, args.output, args.version)
        return

    of = 'pretty-xml' if args.output_format == 'xml' else args.output_format

    if args.command == 'export':
        exportOntology(args, of)
    else:
        updateOntology(args, of)


def run_tool():
    """Entry point for executable script."""
    main(sys.argv[1:])


if __name__ == '__main__':
    run_tool()
