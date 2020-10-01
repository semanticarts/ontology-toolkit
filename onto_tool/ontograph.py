"""
Generates a graphical representation of a collection of ontologies.

It extracts the classes, object properties, data properties (if any),
and entities of subClass "owl:Thing". It establishes the imports for each file,
and then presents the results as a graphviz 'dot' file and a .png file.
@version 2
"""

import logging
import os
import re
import datetime

from rdflib import Graph, BNode
from rdflib.namespace import RDF, OWL
from rdflib.util import guess_format
import pydot

# Ignore \l - uses them as a line separator
# pylint: disable=W1401

class OntoGraf():
    def __init__(self, files, outpath='.', wee=False, title='Gist', version=None):
        self.wee = wee
        if not version:
            version = datetime.datetime.now().isoformat()[:10]
        self.title = f'{title} Ontology: {version}'
        if wee:
            self.graf = pydot.Dot(graph_type='digraph',
                                  label=self.title,
                                  labelloc='t',
                                  rankdir="TB")
        else:
            self.graf = pydot.Dot(graph_type='digraph',
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
        self.files = files
        self.outpath = outpath
        outfilename = f'{title}{version}'
        self.outdot = os.path.join(self.outpath, outfilename + ".dot")
        self.outpng = os.path.join(self.outpath, outfilename + ".png")
        self.outdict = {}
        self.arrowcolor = "darkorange2"
        self.arrowhead = "vee"

    @staticmethod
    def strip_uri(uri):
        return re.sub(r'^.*[/#](gist)?(.*?)(X.x.x|\d+.\d+.\d+)?$', '\\2', str(uri))

    def gather_info(self):
        self.outdict = {}
        for file_path in self.files:
            filename = os.path.basename(file_path)
            logging.debug('Parsing %s for documentation', filename)
            graph = Graph()
            graph.parse(file_path, format=guess_format(file_path))

            ontology = next(graph.subjects(RDF.type, OWL.Ontology))
            ontology_name = self.strip_uri(ontology)
            classes = [self.strip_uri(c) for c in graph.subjects(RDF.type, OWL.Class)
                       if not isinstance(c, BNode)]
            obj_props = [self.strip_uri(c)
                         for c in graph.subjects(RDF.type, OWL.ObjectProperty)]
            data_props = [self.strip_uri(c)
                          for c in graph.subjects(RDF.type, OWL.DatatypeProperty)]
            gist_things = [self.strip_uri(c) for c in graph.subjects(RDF.type, OWL.Thing)]
            imports = [self.strip_uri(c) for c in graph.objects(ontology, OWL.imports)]

            self.outdict[filename] = {
                "ontologyName": ontology_name,
                "classesList": "\\l".join(classes),
                "obj_propertiesList": "\\l".join(obj_props),
                "data_propertiesList": "\\l".join(data_props),
                "gist_thingsList": "\\l".join(gist_things),
                "imports": imports
            }
        return self.outdict

    def create_graf(self, data_dict=None, wee=None):
        if data_dict is None:
            data_dict = self.outdict
        if wee is None:
            wee = self.wee
        for file in data_dict.keys():
            if file != '':
                ontology_name = data_dict[file]["ontologyName"]
                classes = data_dict[file]["classesList"]
                obj_properties = data_dict[file]["obj_propertiesList"]
                data_properties = data_dict[file]["data_propertiesList"]
                gist_things = data_dict[file]["gist_thingsList"]
                imports = data_dict[file]["imports"]
                if wee:
                    node = pydot.Node(ontology_name)
                else:
                    ontology_info = "{{{}\\l\\l{}|{}|{}|{}|{}}}".format(
                        file,
                        ontology_name,
                        classes,
                        obj_properties,
                        data_properties,
                        gist_things)
                    node = pydot.Node(ontology_name,
                                      label=ontology_info)

                self.graf.add_node(node)

                for imported in imports:
                    edge = pydot.Edge(ontology_name, imported,
                                      color=self.arrowcolor,
                                      arrowhead=self.arrowhead)
                    self.graf.add_edge(edge)
        self.graf.write(self.outdot)
        self.graf.write_png(self.outpng)
        logging.debug("Plots saved")
