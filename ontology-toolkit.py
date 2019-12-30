import logging


logging.basicConfig(level=logging.DEBUG)


import argparse
import re
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, OWL, SKOS, NamespaceManager
from rdflib.util import guess_format

parser = argparse.ArgumentParser(description='Ontology toolkit.')
parser.add_argument('--defined-by', action="store_true",
                    help='Add rdfs:isDefinedBy to every resource defined.')
parser.add_argument('--set-version', action="store",
                    help='Set the version of the defined ontology')
parser.add_argument('--dependency-version', action="append",
                    metavar=('DEPENDENCY','VERSION'),
                    nargs=2, default=[], 
                    help='Update the import of DEPENDENCY to VERSION')
parser.add_argument('--nonversioned-dependencies', action="store_true",
                    help='Remove versions from imports.')
parser.add_argument('--output-format', action='store',
                    metavar='FORMAT',
                    default='turtle',
                    choices=['xml','turtle','n3'])
parser.add_argument('ontology', nargs="*", default=[],
                    help="Ontology file")

args = parser.parse_args()
for onto_file in args.ontology:
    g = Graph()
    g.parse(onto_file, format=guess_format(onto_file))
    logging.debug(f'{onto_file} has {len(g)} triples')

    # locate ontology
    ontologies = list(g.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) == 0:
        logging.warning(f'No ontology definition found in {onto_file}')
        continue
    elif len(ontologies) > 1:
        logging.error(f'Multiple ontologies defined in {onto_file}, skipping')
        continue

    ontology = ontologies[0]
    logging.info(f'{ontology} found in {onto_file}')

    ontologyIRI = next(g.objects(ontology, OWL.ontologyIRI), None)
    if ontologyIRI:
        logging.debug(f'{ontologyIRI} found for {ontology}')
    else:
        ontologyIRI = ontology

    # Set version
    if args.set_version:
        g.add((ontology, OWL.ontologyIRI, ontologyIRI))
        logging.debug(f'ontologyIRI {ontologyIRI} added for {ontology}')
        
        oldVersion = next(g.objects(ontology, OWL.versionIRI), None)
        if oldVersion:
            logging.debug(f'Removing versionIRI {oldVersion} from {ontology}')
            g.remove((ontology, OWL.versionIRI, oldVersion))

        versionIRI = URIRef(f"{ontologyIRI}{args.set_version}")
        g.add((ontology, OWL.versionIRI, versionIRI))
        logging.debug(f'versionIRI {versionIRI} added for {ontology}')

    # Add definedBy
    if args.defined_by:
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

    # Update dep versions
    if len(args.dependency_version):
        # Gather current dependencies
        currentDeps = g.objects(ontology, OWL.imports)       
        for dv in args.dependency_version:
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
                
        
    # Remove dep versions

    # Output
    of = 'pretty-xml' if args.output_format == 'xml' else args.output_format
    print(g.serialize(format=of).decode('utf-8'))