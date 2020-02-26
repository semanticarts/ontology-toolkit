import logging
import argparse
import re
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS, XSD
from rdflib.util import guess_format

import pydot
import glob
import os
import datetime
from pprint import pprint


class OntoGraf():
    """from describeGistOWLFiles.v2.py
This is a small routine to describe a collection of Gist OWL files.
It extracts the classes, object properties, data properties (if any), and Gist entities of subClass  "owl:Thing".
It establishes the imports for each file, and then presents the results as a graphviz 'dot' file and a .png file.
@version 2
"""
    def __init__(self, wee=False):
        self.queries = {}
        self.queries["q_classes"] = """prefix : <http://example.com#>  construct {?x :hasClass ?y .} where {?x a owl:Ontology . ?y a owl:Class. FILTER (!isBlank(?y))}"""
        self.queries["q_obj_properties"] = """prefix : <http://example.com#>  construct {?x :hasObjectProperty ?y .} where {?x a owl:Ontology . ?y a owl:ObjectProperty. }"""
        self.queries["q_data_properties"] = """prefix : <http://example.com#>  construct {?x :hasDataProperty ?y .} where {?x a owl:Ontology . ?y a owl:DataProperty. }"""
        self.queries["q_gist_things"] = """prefix : <http://example.com#>  construct {?x :hasGistThing ?y .} where {?x a owl:Ontology . ?y a owl:Thing.  FILTER ( strstarts(str(?y), "https://ontologies.semanticarts.com/gist/") )  }"""
        self.queries["q_imports"] = """prefix : <http://example.com#>  construct {?x :imports ?z .} where {?x a owl:Ontology; owl:imports ?z }"""
        self.title = "Gist Ontology : " + datetime.datetime.now().isoformat()
        if wee:
            self.graf = pydot.Dot(graph_type='digraph', label=self.title, labelloc='t', rankdir="TB")
        else:
            self.graf = pydot.Dot(graph_type='digraph', label=self.title, labelloc='t', rankdir="LR", ranksep="0.5", nodesep="1.25")
        self.graf.set_node_defaults(**{'color': 'lightgray', 'style': 'unfilled', 'shape': 'record', 'fontname': 'Bitstream Vera Sans', 'fontsize': '10'})
        self.filepath = r"./*.owl"
        self.outpath = "."
        self.outfilename = datetime.datetime.now().isoformat()[:10] + "graf_output"
        self.outdot = os.path.join(self.outpath, self.outfilename + ".dot")
        self.outpng = os.path.join(self.outpath, self.outfilename + ".png")
        self.outdict = {}
        self.arrowcolor = "darkorange2"
        self.arrowhead = "vee"
        

    def gatherInfo(self):
        self.outdict = {}
        for i in glob.glob(self.filepath):
            filename = os.path.basename(i)
            print("-"*20,filename,"-"*20)
            g = Graph()
            g.parse(i, format=guess_format(i))
            
            classes = self.tidy_query_results(g.query(self.queries["q_classes"]))
            obj_props = self.tidy_query_results(g.query(self.queries["q_obj_properties"]))
            data_props = self.tidy_query_results(g.query(self.queries["q_data_properties"]))
            gist_things = self.tidy_query_results(g.query(self.queries["q_gist_things"]))
            imports = self.tidy_query_results(g.query(self.queries["q_imports"]))
            
            classesList = ''
            obj_propertiesList = ''
            data_propertiesList = ''
            gist_thingsList = ''
            ontologyName = ''
            importsList = ''
            
            for z in classes:
                ontologyName = z[0]
                classesList += z[2] + "\l"
            for z in obj_props:
                ontologyName = z[0]
                obj_propertiesList += z[2] + "\l"
            for z in data_props:
                ontologyName = z[0]
                data_propertiesList += z[2] + "\l"
            for z in gist_things:
                ontologyName = z[0]
                gist_thingsList += z[2] + "\l"
            for z in imports:
                ontologyName = z[0]
                importsList += z[2] + "\l"
                
            self.outdict[filename]= {"ontologyName": ontologyName,
                                     "classesList": classesList,
                                     "obj_propertiesList" : obj_propertiesList,
                                     "data_propertiesList" : data_propertiesList,
                                     "gist_thingsList" : gist_thingsList,
                                     "imports" :  imports
                                    }
        return self.outdict

    def tidy_query_results(self, res):
        arr = [(s.split("/")[-1].replace("gist",""),p.split("#")[-1],o.split("/")[-1].replace("gist","")) for s,p,o in res]
        return arr        

    def createGraf(self, dataDict=None, wee=False):
        if dataDict is None:
            dataDict = self.outdict
        for k in dataDict.keys():
            if k != '':
                ontologyName = dataDict[k]["ontologyName"]
                classesList = dataDict[k]["classesList"]
                obj_propertiesList = dataDict[k]["obj_propertiesList"]
                data_propertiesList = dataDict[k]["data_propertiesList"]
                gist_thingsList = dataDict[k]["gist_thingsList"]
                
                if wee:
                    node = pydot.Node(ontologyName)
                else:
                    node = pydot.Node(ontologyName, label= "{" + k + r"\l\l" + ontologyName + "|" + classesList + "|" + obj_propertiesList + "|" + data_propertiesList + "|" + gist_thingsList + "}")
                self.graf.add_node(node)
                imports  = dataDict[k]["imports"]
                for x in imports:
                    edge = pydot.Edge(x[0],x[2][:-5], color=self.arrowcolor, arrowhead=self.arrowhead)
                    self.graf.add_edge(edge)
        self.graf.write(self.outdot)
        self.graf.write_png(self.outpng)
        print("Plots saved")



class MergeAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        try:
            iri = URIRef(values[0])
        except Exception as e:
            parser.error(f'Invalid merge ontology URI {values[0]}: {e}')
        if not re.match(r'\d+(\.\d+){0,2}', values[1]):
            parser.error(f'Invalid merge ontology version {values[1]}')
        setattr(namespace, self.dest, [iri, values[1]])


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
    export_parser.add_argument('-m', '--merge', action=MergeAction, nargs=2,
                               metavar=('IRI','VERSION'),
                               help='Merge all inputs into a single ontology'
                               ' with the given IRI and version')
    export_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file")

    graphic_parser = subparsers.add_parser('graphic',help='Create PNG graphic and dot file from OWL files in folder')
    graphic_parser.add_argument('-f', '--from_folder', action="store", help="folder and file pattern (e.g. .\*.owl) for OWL files ")
    graphic_parser.add_argument('-t', '--to_folder', action="store", help="folder where graphic and dot files will be saved")
    graphic_parser.add_argument('-w', '--wee_pic', action="store", help="a version of the graphic with only core information about ontology and imports")
    
    

    
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


def stripVersions(g, ontology=None):
    # Gather current dependencies
    ontologies = [ontology] if ontology else list(g.subjects(RDF.type, OWL.Ontology))
    for o in ontologies:
        currentDeps = g.objects(o, OWL.imports)
        pattern = re.compile('^(.*?)((\d+|[Xx])\.(\d+|[Xx])\.(\d+|[Xx]))?$')
        for d in currentDeps:
            match = pattern.match(str(d))
            if match.group(2):
                logging.debug(f'Removing version for {d}')
                g.remove((o, OWL.imports, d))
                g.add((o, OWL.imports, URIRef(match.group(1))))


def versionSensitiveMatch(reference, ontologies):
    match = re.match(r'^(.*?)((\d+|[Xx])\.(\d+|[Xx])\.(\d+|[Xx]))?$',
                     str(reference))
    refWithoutVersion = match.group(1)
    return URIRef(refWithoutVersion) in ontologies


def cleanMergeArtifacts(g, iri, version):
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


def main():
    logging.basicConfig(level=logging.DEBUG)

    args = configureArgParser().parse_args()
    g = None

    of = 'pretty-xml' if args.output_format == 'xml' else args.output_format

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
        
    elif 'from_folder' in args:

        if "wee_pic":
            graf = OntoGraf(wee=True)
            graf.filepath = args.from_folder
            graf.outpath = args.to_folder
            graf.gatherInfo()
            graf.createGraf(wee=True)
        else:
            graf = OntoGraf()
            graf.filepath = args.from_folder
            graf.outpath = args.to_folder
            graf.gatherInfo()                 
            graf.createGraf()
        print(graf.outdot + " and " + graf.outpng + "written to " + graf.outpath)
        
        
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
            print(g.serialize(format=of).decode('utf-8'))


if __name__ == '__main__':
    main()
