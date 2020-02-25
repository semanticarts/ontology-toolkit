from rdflib import Graph, BNode
from rdflib.namespace import RDF, OWL
from rdflib.util import guess_format

import logging
import pydot
import os
import re
import datetime

"""from onto-graph.py
This is a small routine to describe a collection of Gist OWL files.
It extracts the classes, object properties, data properties (if any), and Gist entities of subClass  "owl:Thing".
It establishes the imports for each file, and then presents the results as a graphviz 'dot' file and a .png file.
@version 2
"""

class OntoGraf():
    def __init__(self, files, outpath='.', title='Gist', version=None):
        if not version:
            version = datetime.datetime.now().isoformat()
        self.title = f'{title} Ontology: {version}'

        self.graf = pydot.Dot(
                graph_type='digraph',
                label=self.title,
                labelloc='t',
                rankdir="LR",
                ranksep="0.5",
                nodesep="1.25")
        self.graf.set_node_defaults(**{
                'color': 'lightgray',
                'style': 'unfilled',
                'shape': 'record',
                'fontname': 'Bitstream Vera Sans',
                'fontsize': '10'
            })
        self.filepath = files
        self.outpath = outpath
        self.outfilename = f'{title}{version}'
        self.outdot = os.path.join(self.outpath, self.outfilename + ".dot")
        self.outpng = os.path.join(self.outpath, self.outfilename + ".png")
        self.outdict = {}
        self.arrowcolor = "darkorange2"
        self.arrowhead = "vee"

    def strip_uri(self, uri):
        return re.sub(r'^.*[/#](gist)?(.*?)(X.x.x)?$', '\\2', str(uri))

    def gatherInfo(self):
        self.outdict = {}
        for i in self.filepath:
            filename = os.path.basename(i)
            logging.debug(f'Parsing {filename} for documentation')
            g = Graph()
            g.parse(i, format=guess_format(i))

            ontology = next(g.subjects(RDF.type, OWL.Ontology))
            ontologyName = self.strip_uri(ontology)
            classes = [self.strip_uri(c) for c in g.subjects(RDF.type, OWL.Class)
                if not isinstance(c, BNode)]
            obj_props = [self.strip_uri(c) for c in g.subjects(RDF.type, OWL.ObjectProperty)]
            data_props = [self.strip_uri(c) for c in g.subjects(RDF.type, OWL.DatatypeProperty)]
            gist_things = [self.strip_uri(c) for c in g.subjects(RDF.type, OWL.Thing)]
            imports = [self.strip_uri(c) for c in g.objects(ontology, OWL.imports)]

            self.outdict[filename]= {
                    "ontologyName": ontologyName,
                    "classesList": "\l".join(classes),
                    "obj_propertiesList" : "\l".join(obj_props),
                    "data_propertiesList" : "\l".join(data_props),
                    "gist_thingsList" : "\l".join(gist_things),
                    "imports" : imports
            }
        return self.outdict

    def createGraf(self, dataDict=None):
        if dataDict is None:
            dataDict = self.outdict
        for k in dataDict.keys():
            if k != '':
                ontologyName = dataDict[k]["ontologyName"]
                classesList = dataDict[k]["classesList"]
                obj_propertiesList = dataDict[k]["obj_propertiesList"]
                data_propertiesList = dataDict[k]["data_propertiesList"]
                gist_thingsList = dataDict[k]["gist_thingsList"]
                imports  = dataDict[k]["imports"]

                node = pydot.Node(ontologyName,
                                  label= "{" + k + r"\l\l"
                                  + ontologyName + "|"
                                  + classesList + "|"
                                  + obj_propertiesList + "|"
                                  + data_propertiesList + "|"
                                  + gist_thingsList + "}")
                self.graf.add_node(node)

                for i in imports:
                    edge = pydot.Edge(
                            ontologyName, i,
                            color=self.arrowcolor,
                            arrowhead=self.arrowhead)
                    self.graf.add_edge(edge)
        self.graf.write(self.outdot)
        self.graf.write_png(self.outpng)
        logging.debug("Plots saved")
