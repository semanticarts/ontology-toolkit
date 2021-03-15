"""
Generates a graphical representation of a collection of ontologies.

It extracts the classes, object properties, data properties (if any),
and entities of subClass "owl:Thing". It establishes the imports for each file,
and then presents the results as a graphviz 'dot' file and a .png file.
@version 2
"""

import datetime
import logging
import os
import re
import sys
from collections import defaultdict
from math import log
from string import Template
from time import perf_counter
from urllib.parse import urlparse, urlunparse

import pydot
from SPARQLWrapper import SPARQLWrapper, POST, BASIC, JSON
from rdflib import Graph, BNode
from rdflib.namespace import RDF, OWL
from rdflib.util import guess_format


# Ignore \l - uses them as a line separator
# pylint: disable=W1401

class OntoGraf():
    def __init__(self, files, repo=None, **kwargs):
        self.wee = kwargs.get('wee', False)
        title = kwargs.get('title', 'Gist')
        version = kwargs.get('version')
        if not version:
            version = datetime.datetime.now().isoformat()[:10]
        if repo:
            self.title = self.anonymize_url(repo) + ': ' + version
            out_filename = 'repo'
        else:
            self.title = f'{title} Ontology: {version}'
            out_filename = f'{title}{version}'
        self.graf = None
        self.files = files
        self.repo = repo

        outpath = kwargs.get('outpath', '.')
        self.outpath = outpath
        if os.path.isdir(outpath):
            self.outdot = os.path.join(self.outpath, out_filename + ".dot")
            self.outpng = os.path.join(self.outpath, out_filename + ".png")
        else:
            self.outdot = self.outpath + ".dot"
            self.outpng = self.outpath + ".png"

        self.limit = kwargs.get('limit', 500000)
        self.threshold = kwargs.get('threshold', 10)
        self.node_data = {}
        self.arrowcolor = "darkorange2"
        self.arrowhead = "vee"

    @staticmethod
    def anonymize_url(url):
        parsed = urlparse(url)
        return urlunparse((parsed.scheme,
                           re.sub('^.*@', '', parsed.netloc),
                           parsed.path,
                           '', '', ''))

    def select_query(self, query):
        """Execute SPARQL SELECT query, return results as generator."""
        logging.debug(f"Query against {self.repo}")
        logging.debug(f"Query\n {query}")

        repo_url = urlparse(self.repo)

        sparql = SPARQLWrapper(urlunparse((repo_url.scheme,
                                           re.sub('^.*@', '', repo_url.netloc),
                                           repo_url.path,
                                           '', '', '')))

        sparql.setHTTPAuth(BASIC)
        sparql.setCredentials(repo_url.username, repo_url.password)
        sparql.setMethod(POST)

        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        results = sparql.query().convert()

        for result in results["results"]["bindings"]:
            yield dict(
                (v, result[v]["value"])
                for v in results["head"]["vars"] if v in result
            )

    @staticmethod
    def strip_uri(uri):
        return re.sub(r'^.*[/#](gist)?(.*?)(X.x.x|\d+.\d+.\d+)?$', '\\2', str(uri))

    def gather_schema_info_from_files(self):
        self.node_data = {}
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

            self.node_data[filename] = {
                "ontologyName": ontology_name,
                "classesList": "\\l".join(classes),
                "obj_propertiesList": "\\l".join(obj_props),
                "data_propertiesList": "\\l".join(data_props),
                "gist_thingsList": "\\l".join(gist_things),
                "imports": imports
            }
        return self.node_data

    def gather_schema_info_from_repo(self):
        onto_data = defaultdict(lambda: defaultdict(list))
        onto_query = """
        prefix owl: <http://www.w3.org/2002/07/owl#>
        prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        prefix xsd: <http://www.w3.org/2001/XMLSchema#>
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix gist: <https://ontologies.semanticarts.com/gist/>
        
        select ?ontology ?entity ?type where {
          ?ontology a owl:Ontology .
          {
            ?ontology owl:imports ?entity .
            BIND(owl:imports as ?type)
          }
          UNION
          {
            ?entity rdfs:isDefinedBy ?ontology; a/rdfs:subClassOf* gist:Category .
            BIND(owl:Thing as ?type)
          }
          UNION
          {
            values ?type { owl:Class owl:DatatypeProperty owl:ObjectProperty owl:Thing }
            ?entity rdfs:isDefinedBy ?ontology; a ?type .
            filter(!ISBLANK(?entity))
          }
        }
        """
        mapping = {
            str(OWL.Class): 'classesList',
            str(OWL.ObjectProperty): 'obj_propertiesList',
            str(OWL.DatatypeProperty): 'data_propertiesList',
            str(OWL.Thing): 'gist_thingsList',
            'https://ontologies.semanticarts.com/gist/Category': 'gist_thingsList',
            str(OWL.imports): 'imports'
        }
        for entity in self.select_query(onto_query):
            onto_data[entity['ontology']][mapping[entity['type']]].append(self.strip_uri(entity['entity']))

        self.node_data = defaultdict(dict)
        for ontology, props in onto_data.items():
            self.node_data[ontology]['ontologyName'] = self.strip_uri(ontology)
            for key in set(mapping.values()):
                if key != 'imports':
                    self.node_data[ontology][key] = "\\l".join(sorted(props[key])) if key in props else ''
                else:
                    self.node_data[ontology][key] = props[key] if key in props else []
        return self.node_data

    def create_schema_graf(self, data_dict=None, wee=None):
        if data_dict is None:
            data_dict = self.node_data
        if wee is None:
            wee = self.wee
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
        for file, file_data in data_dict.items():
            if file != '':
                ontology_name = file_data["ontologyName"]
                classes = file_data["classesList"]
                obj_properties = file_data["obj_propertiesList"]
                data_properties = file_data["data_propertiesList"]
                gist_things = file_data["gist_thingsList"]
                imports = file_data["imports"]
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

    # Print iterations progress
    @staticmethod
    def print_progress_bar(iteration, total,
                           prefix='', suffix='', decimals=1, length=100,
                           fill='X', printEnd="\r"):
        """
        Stolen from https://stackoverflow.com/questions/3173320/text-progress-bar-in-the-console
        Call in a loop to create terminal progress bar
        @params:
            iteration   - Required  : current iteration (Int)
            total       - Required  : total iterations (Int)
            prefix      - Optional  : prefix string (Str)
            suffix      - Optional  : suffix string (Str)
            decimals    - Optional  : positive number of decimals in percent complete (Int)
            length      - Optional  : character length of bar (Int)
            fill        - Optional  : bar fill character (Str)
            printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
        """
        # if not sys.stdout.isatty():
        #     return
        percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
        filled_length = int(length * iteration // total)
        bar = fill * filled_length + '-' * (length - filled_length)
        print(f'\r{prefix} |{bar}| {percent}% {suffix}', end=printEnd)
        # Print New Line on Complete
        if iteration == total:
            print()
        sys.stdout.flush()

    def gather_instance_info_from_repo(self):
        predicate_query = """
        prefix owl: <http://www.w3.org/2002/07/owl#>
        prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        prefix xsd: <http://www.w3.org/2001/XMLSchema#>
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix gist: <https://ontologies.semanticarts.com/gist/>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>

        select distinct ?predicate ?label ?type where {
          ?s ?predicate ?o
          FILTER(?predicate NOT IN (rdf:type, skos:prefLabel, skos:definition))
          FILTER (!STRSTARTS(STR(?predicate), 'http://www.w3.org/2002/07/owl#'))
          FILTER (!STRSTARTS(STR(?predicate), 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'))
          FILTER (!STRSTARTS(STR(?predicate), 'http://www.w3.org/2000/01/rdf-schema#'))
          OPTIONAL {
            ?predicate skos:prefLabel|rdfs:label ?label
          }
          OPTIONAL {
            values ?type { owl:DatatypeProperty owl:ObjectProperty }
            ?predicate a ?type
          }
        }
        """
        self.node_data = {}
        all_predicates = list(self.select_query(predicate_query))
        for count, pred_row in enumerate(all_predicates):
            predicate_str = pred_row['label'] if pred_row.get('label') \
                else self.strip_uri(pred_row['predicate'])

            self.print_progress_bar(count, len(all_predicates),
                                    prefix='Processing predicates:',
                                    suffix=predicate_str + ' ' * 20, length=50)
            pre_time = perf_counter()
            pred_type = pred_row.get('type')
            if pred_type == str(OWL.ObjectProperty):
                type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>

                select ?src ?srcLabel
                       ?tgt ?tgtLabel
                       ?num
                where {
                  {
                    select ?src ?tgt (COUNT(?src) as ?num) where {
                      {
                        select ?src ?tgt where {
                          ?s <$pred> ?o .
                          FILTER(!ISBLANK(?s))
                          ?s a ?src .
                          FILTER (!STRSTARTS(STR(?src), 'http://www.w3.org/2002/07/owl#'))
                          ?o a ?tgt .
                        } LIMIT $limit
                      }
                    } group by ?src ?tgt
                  }
                  OPTIONAL { ?src skos:prefLabel|rdfs:label ?srcLabel }
                  OPTIONAL { ?tgt skos:prefLabel|rdfs:label ?tgtLabel }
                }
                """
            elif pred_type == str(OWL.DatatypeProperty):
                type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>

                select ?src ?srcLabel
                       ?dt
                       ?num
                where {
                  {
                    select ?src ?dt (COUNT(?src) as ?num) where {
                      {
                        select ?src ?dt where {
                          ?s <$pred> ?o .
                          FILTER(!ISBLANK(?s))
                          ?s a ?src .
                          FILTER (!STRSTARTS(STR(?src), 'http://www.w3.org/2002/07/owl#'))
                          BIND(DATATYPE(?o) as ?dt) .
                        } LIMIT $limit
                      }
                    } group by ?src ?dt
                  }
                  OPTIONAL { ?src skos:prefLabel|rdfs:label ?srcLabel }
                }
                """
            else:
                type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>

                select ?src ?srcLabel
                       ?tgt ?tgtLabel
                       ?dt
                       ?num
                where {
                  {
                    {
                      select ?src ?tgt (COUNT(?src) as ?num) where {
                        {
                          select ?src ?tgt where {
                            ?s <$pred> ?o .
                            FILTER(!ISBLANK(?s))
                            ?s a ?src .
                            FILTER (!STRSTARTS(STR(?src), 'http://www.w3.org/2002/07/owl#'))
                            ?o a ?tgt .
                          } LIMIT $limit
                        }
                      } group by ?src ?tgt
                    }
                    OPTIONAL { ?src skos:prefLabel|rdfs:label ?srcLabel }
                    OPTIONAL { ?tgt skos:prefLabel|rdfs:label ?tgtLabel }
                  }
                  UNION
                  {
                    {
                      select ?src ?dt (COUNT(?src) as ?num) where {
                        {
                          select ?src ?dt where {
                            ?s <$pred> ?o .
                            FILTER(!ISBLANK(?s))
                            FILTER(isLITERAL(?o))
                            ?s a ?src .
                            FILTER (!STRSTARTS(STR(?src), 'http://www.w3.org/2002/07/owl#'))
                            BIND(DATATYPE(?o) as ?dt) .
                          } LIMIT $limit
                        }
                      } group by ?src ?dt
                    }
                    OPTIONAL { ?src skos:prefLabel|rdfs:label ?srcLabel }
                  }
                }
                """
            query_text = Template(type_query).substitute(pred=pred_row['predicate'],
                                                         limit=self.limit)
            for type_row in self.select_query(query_text):
                if 'src' not in type_row or int(type_row.get('num', 0)) < self.threshold:
                    continue
                if type_row['src'] not in self.node_data:
                    src = {
                        'label': type_row.get('srcLabel'),
                        'links': {},
                        'data': {}
                    }
                    self.node_data[type_row['src']] = src
                else:
                    src = self.node_data[type_row['src']]
                if type_row.get('dt'):
                    src['data'][(predicate_str, self.strip_uri(type_row['dt']))] = int(type_row['num'])
                else:
                    if type_row['tgt'] not in self.node_data:
                        self.node_data[type_row['tgt']] = {
                            'label': type_row.get('tgtLabel'),
                            'links': {},
                            'data': {}
                        }
                    src['links'][(predicate_str, type_row['tgt'])] = int(type_row['num'])

            logging.debug("Fetching %s took %d seconds", str(pred_row), perf_counter() - pre_time)

        self.print_progress_bar(len(all_predicates), len(all_predicates),
                                prefix='Processing predicates:', suffix='Complete', length=50)

    @staticmethod
    def line_width(num_used):
        return min(5, max(1, round(log(num_used, 100))))

    def create_instance_graf(self, data_dict=None):
        self.graf = pydot.Dot(graph_type='digraph',
                              label=self.title,
                              labelloc='t',
                              rankdir="LR",
                              ranksep="0.5")

        self.graf.set_node_defaults(**{
            'color': 'lightgray',
            'style': 'unfilled',
            'shape': 'record',
            'fontname': 'Bitstream Vera Sans',
            'fontsize': '10'
        })
        if data_dict is None:
            data_dict = self.node_data
        for class_, class_data in data_dict.items():
            class_info = "{}|{}".format(
                class_data['label'] if class_data['label'] else self.strip_uri(class_),
                "\\l".join(f"{prop}: {dt}" for prop, dt in class_data['data'].keys()))
            node = pydot.Node(name='"' + class_ + '"',
                              label=class_info)

            self.graf.add_node(node)

            for link, num in class_data['links'].items():
                pred, target = link
                edge = pydot.Edge(class_, target,
                                  label=pred,
                                  penwidth=self.line_width(num),
                                  color=self.arrowcolor,
                                  arrowhead=self.arrowhead)
                self.graf.add_edge(edge)

        self.graf.write(self.outdot)
        self.graf.write_png(self.outpng)
        logging.debug("Plots saved")
