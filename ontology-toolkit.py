import logging
import argparse
import re
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
from rdflib.util import guess_format


def configureArgParser():
    parser = argparse.ArgumentParser(description='Ontology toolkit.')
    parser.add_argument('-o', '--output-format', action='store',
                        default='turtle',
                        choices=['xml','turtle','n3'],
                        help='Output format')
    subparsers = parser.add_subparsers(help='sub-command help')

    update_parser = subparsers.add_parser('update',help='Update versions and dependencies')
    update_parser.add_argument('-b', '--defined-by', action="store_true",
                               help='Add rdfs:isDefinedBy to every resource defined.')
    update_parser.add_argument('-v', '--set-version', action="store",
                               help='Set the version of the defined ontology')
    update_parser.add_argument('-i', '--version-info', action="store",
                               nargs='?', const='auto',
                               help='Adjust versionInfo, defaults to "Version X.x.x')
    update_parser.add_argument('-d','--dependency-version', action="append",
                               metavar=('DEPENDENCY','VERSION'),
                               nargs=2, default=[],
                               help='Update the import of DEPENDENCY to VERSION')
    update_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file")

    export_parser = subparsers.add_parser('export',help='Export ontology')
    export_parser.add_argument('-s', '--strip-versions', action="store_true",
                               help='Remove versions from imports.')
    export_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file")
    return parser


def findSingleOntology(g, onto_file):
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
    pattern = re.compile('^(.*?)(\d+\.\d+\.\d+)?$')
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
    definitions = g.query("""
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
                logging.warning(f'{d.defined} defined by {d.defBy} instead of {ontologyIRI}')
        else:
            logging.debug(f'Added definedBy to {d.defined}')
            g.add((d.defined, RDFS.isDefinedBy, ontologyIRI))


def updateDependencyVersions(g, ontology, versions):
    # Gather current dependencies
    currentDeps = g.objects(ontology, OWL.imports)
    for dv in versions:
        dep, ver = dv
        pattern = re.compile(f'{dep}(\d+\.\d+\.\d+)?')
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


def stripVersions(g, ontology):
    # Gather current dependencies
    currentDeps = g.objects(ontology, OWL.imports)
    pattern = re.compile('^(.*)(\d+\.\d+\.\d+)?')
    for d in currentDeps:
        match = pattern.match(str(d))
        if match.group(2):
            logging.debug(f'Removing version for {d}')
            g.remove((ontology, OWL.imports, d))
            g.add((ontology, OWL.imports, URIRef(match.group(1))))


def main():
    logging.basicConfig(level=logging.DEBUG)

    args = configureArgParser().parse_args()

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
        if 'set_version' in args:
            setVersion(g, ontology, ontologyIRI, args.set_version)
        if 'version_info' in args:
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
        of = 'pretty-xml' if args.output_format == 'xml' else args.output_format
        print(g.serialize(format=of).decode('utf-8'))


if __name__ == '__main__':
    main()
