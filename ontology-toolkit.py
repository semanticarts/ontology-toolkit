"""Toolkit for ontology maintenance and release."""
import logging
import argparse
import os
from os.path import join, isdir, isfile, basename, splitext
from glob import glob
import re
import subprocess
import shutil
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
from rdflib.util import guess_format
from ontograph import OntoGraf
import mdutils


class OntologyUriValidator(argparse.Action):
    """Validates ontology IRI and version arguments."""

    def __call__(self, parser, namespace, values, option_string=None):
        """First argument is a valid URI, 2nd a valid semantic version."""
        try:
            iri = URIRef(values[0])
        except Exception as e:
            parser.error(f'Invalid merge ontology URI {values[0]}: {e}')
        if not re.match(r'\d+(\.\d+){0,2}', values[1]):
            parser.error(f'Invalid merge ontology version {values[1]}')
        setattr(namespace, self.dest, [iri, values[1]])


def configureArgParser():
    """Configure command line parser."""
    parser = argparse.ArgumentParser(description='Ontology toolkit.')
    parser.add_argument('--output-format', action='store',
                        default='turtle',
                        choices=['xml', 'turtle', 'n3'],
                        help='Output format')
    subparsers = parser.add_subparsers(help='sub-command help', dest='command')

    update_parser = subparsers.add_parser('update',
                                          help='Update versions and dependencies')
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
                               help="Ontology file")

    export_parser = subparsers.add_parser('export', help='Export ontology')
    export_parser.add_argument('-s', '--strip-versions', action="store_true",
                               help='Remove versions from imports.')
    export_parser.add_argument('-m', '--merge', action=OntologyUriValidator, nargs=2,
                               metavar=('IRI', 'VERSION'),
                               help='Merge all inputs into a single ontology'
                               ' with the given IRI and version')
    export_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file")

    bundle_parser = subparsers.add_parser('bundle', help='Bundle ontology for release')
    bundle_parser.add_argument('-t', '--tools', action="store",
                               help="Location of serializer tool")
    bundle_parser.add_argument('-a', '--artifacts', action="store",
                               help="Location of release artifacts "
                               "(release notes, license, etc), defaults to "
                               "current working directory",
                               default=os.getcwd())
    bundle_parser.add_argument('-c', '--catalog', action="store",
                               help="Location of Protege catalog, defaults to "
                               "OntologyFiles/bundle-catalog-v001.xml in the "
                               "artifacts directory")
    bundle_parser.add_argument('-o', '--output', action="store",
                               help="Output directory for transformed ontology files")
    bundle_parser.add_argument('version', help="Version string to replace X.x.x template")
    bundle_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file, directory or name pattern")

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
    elif len(ontologies) > 1:
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
          VALUES ?dtype { owl:Class owl:ObjectProperty owl:DatatypeProperty }
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
    elif isdir(path):
        return glob(join(path, '*.owl'))
    else:
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


def updateVersion(file, version):
    """Substitute version placeholder for actual version in file."""
    with open(file, 'r') as f:
        replaced = f.read().replace('X.x.x', version)
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


def bundleOntology(args):
    """Bundle ontology and related artifacts for release."""
    output = args.output if args.output else \
        join(os.getcwd(), f"gist{args.version}_webDownload")
    if not isdir(output):
        os.mkdir(output)

    if len(args.ontology) == 0:
        specifiedFiles = [join(args.artifacts, 'OntologyFiles')]
    else:
        specifiedFiles = args.ontology
    allFiles = [file for ref in specifiedFiles for file in expandFileRef(ref)]
    for file in allFiles:
        serialized = serializeToOutputDir(
                args.tools if args.tools else join(args.artifacts, 'tools'),
                output,
                args.version,
                file)
        updateVersion(serialized, args.version)

    copyIfPresent(join(args.artifacts, 'LICENSE.txt'), output)
    copyIfPresent(join(args.artifacts, 'doc', 'ReleaseNotes.md'), output)
    if isfile(join(output, 'ReleaseNotes.md')):
        conv = mdutils.md2html()
        filepath_in = join(output, 'ReleaseNotes.md')
        filepath_out = join(output, 'ReleaseNotes.html')
        md = open(filepath_in).read()
        converted_md = conv.md2html(md)
        with open(filepath_out, 'w') as fd:
            converted_md.seek(0)
            shutil.copyfileobj(converted_md, fd, -1)

    catalog = args.catalog if args.catalog else \
        join(args.artifacts, 'OntologyFiles', 'bundle-catalog-v001.xml')
    if isfile(catalog):
        copied = join(output, 'catalog-v001.xml')
        shutil.copy(catalog, copied)
        updateVersion(copied, args.version)

    deprecated = join(output, 'Deprecated')
    if not isdir(deprecated):
        os.mkdir(deprecated)
    for d in glob(join(output, '*Deprecated*')):
        shutil.move(d, deprecated)

    documentation = join(output, 'Documentation')
    if not isdir(documentation):
        os.mkdir(documentation)
    og = OntoGraf([f for f in allFiles if 'Deprecated' not in f],
                  outpath=documentation, version=args.version)
    og.gatherInfo()
    og.createGraf()


def main():
    """Do the thing."""
    logging.basicConfig(level=logging.DEBUG)

    args = configureArgParser().parse_args()
    g = None

    of = 'pretty-xml' if args.output_format == 'xml' else args.output_format

    if args.command == 'bundle':
        return bundleOntology(args)

    if args.command == 'graphic':
        return generateGraphic(args.ontology, args.wee, args.output, args.version)

    if 'merge' in args and args.merge:
        g = Graph()
        for onto_file in args.ontology:
            g.parse(onto_file, format=guess_format(onto_file))
            logging.debug(f'{onto_file} has {len(g)} triples')

            # Remove dep versions
            if 'strip_versions' in args and args.strip_versions:
                stripVersions(g)

        cleanMergeArtifacts(g, URIRef(args.merge[0]), args.merge[1])
        print(g.serialize(format=of).decode('utf-8'))
    else:
        for onto_file in args.ontology:
            g = Graph()
            g.parse(onto_file, format=guess_format(onto_file))
            logging.debug(f'{onto_file} has {len(g)} triples')

            # locate ontology
            ontology = findSingleOntology(g, onto_file)
            if not ontology:
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
            if 'dependency_version' in args and len(args.dependency_version):
                updateDependencyVersions(g, ontology, args.dependency_version)

            # Remove dep versions
            if 'strip_versions' in args and args.strip_versions:
                stripVersions(g, ontology)

            # Output
            print(g.serialize(format=of).decode('utf-8'))


if __name__ == '__main__':
    main()
