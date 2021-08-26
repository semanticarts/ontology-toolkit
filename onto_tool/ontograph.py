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
from math import log, pow
from string import Template
from time import perf_counter
from urllib.parse import urlparse, urlunparse

import pydot
from rdflib import Graph, BNode
from rdflib.namespace import RDF, OWL
from rdflib.util import guess_format

from .sparql_utils import create_endpoint, select_query


# Ignore \l - uses them as a line separator
# pylint: disable=W1401

class OntoGraf:
    def __init__(self, files, repo=None, **kwargs):
        self.wee = kwargs.get('wee', False)
        title = kwargs.get('title')
        version = kwargs.get('version')
        if not version:
            version = datetime.datetime.now().isoformat()[:10]
        if repo:
            anonymized, repo_base = self.anonymize_url(repo)
            self.title = (title or anonymized) + ': ' + version
            out_filename = repo_base
        else:
            self.title = f'{title or "Gist"} Ontology: {version}'
            out_filename = f'{title or "Gist"}{version}'
        self.graf = None
        self.files = files
        self.repo = repo
        self.data = None
        self.no_image = kwargs.get('no_image', False)
        self.single_graph = kwargs.get('single_graph', False)

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
        self.arrow_color = "darkorange2"
        self.shacl_color = "darkgreen"
        self.arrowhead = "vee"

        self.include = kwargs.get('include')
        self.exclude = kwargs.get('exclude')
        self.include_pattern = kwargs.get('include_pattern')
        self.exclude_pattern = kwargs.get('exclude_pattern')

        self.superclasses = defaultdict(list)

        self.show_shacl = kwargs.get('show_shacl')
        self.shapes = defaultdict(list)

    @staticmethod
    def anonymize_url(url):
        """Remove username and password from URI, if present."""
        parsed = urlparse(url)
        anonymized = urlunparse((parsed.scheme,
                                 re.sub('^.*@', '', parsed.netloc),
                                 parsed.path,
                                 '', '', ''))
        return anonymized, os.path.basename(parsed.path)

    def select_query(self, query):
        """Execute SPARQL SELECT query, return results as generator."""
        logging.debug(f"Query against {self.repo}")
        logging.debug(f"Query\n {query}")

        sparql = create_endpoint(self.repo)
        return select_query(sparql, query)

    def graph_select_query(self, query):
        """Execute SPARQL SELECT query on local data, return results as generator."""
        results = self.data.query(query)
        for result in results:
            yield dict((str(k), str(v)) for k, v in zip(results.vars, result))

    @staticmethod
    def strip_uri(uri):
        stripped = re.sub(r'^.*[/#](.*?)(X.x.x|\d+.\d+.\d+)?$', '\\1',
                          re.sub(r'[#/]$', '', str(uri)))
        if not stripped:
            logging.warning("Stripping %s went horribly wrong", uri)
            return uri
        return stripped

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
            annotation_props = [self.strip_uri(c)
                                for c in graph.subjects(RDF.type, OWL.AnnotationProperty)]
            all_seen = set(classes + obj_props + data_props + annotation_props)
            gist_things = [self.strip_uri(s) for (s, o) in graph.subject_objects(RDF.type)
                           if not isinstance(s, BNode) and not s == ontology and not self.strip_uri(s) in all_seen]
            imports = [self.strip_uri(c) for c in graph.objects(ontology, OWL.imports)]

            self.node_data[filename] = {
                "ontology": ontology,
                "ontologyName": ontology_name,
                "classesList": "\\l".join(classes),
                "obj_propertiesList": "\\l".join(obj_props),
                "data_propertiesList": "\\l".join(data_props),
                "annotation_propertiesList": "\\l".join(annotation_props),
                "gist_thingsList": "\\l".join(gist_things),
                "imports": imports
            }
        return self.node_data

    def gather_schema_info_from_repo(self):
        onto_data = defaultdict(lambda: defaultdict(list))
        if self.single_graph:
            onto_query = """
            prefix owl: <http://www.w3.org/2002/07/owl#>
            prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            prefix xsd: <http://www.w3.org/2001/XMLSchema#>
            prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            prefix gist: <https://ontologies.semanticarts.com/gist/>

            select ?ontology ?entity ?type where {
              graph ?g {
                ?ontology a owl:Ontology .
                {
                  ?ontology owl:imports ?entity .
                  BIND(owl:imports as ?type)
                }
                UNION
                {
                  ?entity a ?type .
                  FILTER(?type != owl:Ontology)
                  filter(!ISBLANK(?entity))
                }
              }
            }
            """
        else:
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
                ?entity rdfs:isDefinedBy ?ontology; a ?type .
                filter(!ISBLANK(?entity))
              }
            }
            """
        mapping = {
            str(OWL.Class): 'classesList',
            str(OWL.ObjectProperty): 'obj_propertiesList',
            str(OWL.DatatypeProperty): 'data_propertiesList',
            str(OWL.AnnotationProperty): 'annotation_propertiesList',
            str(OWL.imports): 'imports'
        }
        for entity in self.select_query(onto_query):
            key = mapping.get(entity['type'], 'gist_thingsList')
            onto_data[entity['ontology']][key].append(self.strip_uri(entity['entity']))

        if not onto_data:
            logging.warning('Could not find any ontology entities in %s', self.repo)
            return

        self.node_data = defaultdict(dict)
        for ontology, props in onto_data.items():
            self.node_data[ontology]['ontology'] = ontology
            self.node_data[ontology]['ontologyName'] = self.strip_uri(ontology)
            for key in set(mapping.values()).union(set(['gist_thingsList'])):
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
                ontology = file_data["ontology"]
                if not self.ontology_matches_filter(ontology):
                    logging.debug("Filtered out %s", ontology)
                    continue
                ontology_name = file_data["ontologyName"]
                classes = file_data["classesList"]
                obj_properties = file_data["obj_propertiesList"]
                data_properties = file_data["data_propertiesList"]
                annotation_properties = file_data["annotation_propertiesList"]
                gist_things = file_data["gist_thingsList"]
                imports = file_data["imports"]
                if wee:
                    node = pydot.Node(ontology_name)
                else:
                    ontology_info = "{{{}\\l\\l{}|{}|{}|{}|{}|{}}}".format(
                        file,
                        ontology_name,
                        classes,
                        obj_properties,
                        data_properties,
                        annotation_properties,
                        gist_things)
                    node = pydot.Node(ontology_name,
                                      label=ontology_info)

                self.graf.add_node(node)

                for imported in imports:
                    edge = pydot.Edge(ontology_name, imported,
                                      color=self.arrow_color,
                                      arrowhead=self.arrowhead)
                    self.graf.add_edge(edge)
        self.graf.write(self.outdot)
        if not self.no_image:
            self.graf.write_png(self.outpng)
        logging.debug("Plots saved")

    # Print iterations progress
    @staticmethod
    def print_progress_bar(iteration, total,
                           prefix='', suffix='', decimals=1, length=100,
                           fill='X', print_end="\r"):
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
            print_end   - Optional  : end character (e.g. "\r", "\r\n") (Str)
        """
        # if not sys.stdout.isatty():
        #     return
        percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
        filled_length = int(length * iteration // total)
        bar = fill * filled_length + '-' * (length - filled_length)
        print(f'\r{prefix} |{bar}| {percent}% {suffix}', end=print_end)
        # Print New Line on Complete
        if iteration == total:
            print()
        sys.stdout.flush()

    def gather_instance_info(self):
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
        if self.repo:
            all_predicates = list(self.select_query(predicate_query))
        else:
            self.data = Graph()
            for file_path in self.files:
                filename = os.path.basename(file_path)
                logging.debug('Parsing %s for documentation', filename)
                self.data.parse(file_path, format=guess_format(file_path))
            all_predicates = list(self.graph_select_query(predicate_query))

        if not all_predicates:
            logging.warning('No interesting predicates found in %s', self.repo or ' specified files')
            return

        for count, predicate_row in enumerate(all_predicates):
            predicate = predicate_row['predicate']
            predicate_str = predicate_row['label'] if predicate_row.get('label') \
                else self.strip_uri(predicate)

            if logging.root.getEffectiveLevel() != logging.DEBUG:
                self.print_progress_bar(count, len(all_predicates),
                                        prefix='Processing predicates:',
                                        suffix=predicate_str + ' ' * 20, length=50)
            pre_time = perf_counter()
            query_text = self.create_predicate_query(predicate, predicate_row.get('type'), self.limit)
            if self.repo:
                predicate_usage = list(self.select_query(query_text))
            else:
                predicate_usage = list(self.graph_select_query(query_text))
            logging.debug("%s items returned for %s", len(predicate_usage), predicate)
            for usage in predicate_usage:
                if 'src' not in usage or int(usage.get('num', 0)) < self.threshold:
                    continue
                self.record_predicate_usage(predicate, predicate_str, usage)

            logging.debug("Fetching %s took %d seconds", str(predicate_row), perf_counter() - pre_time)

        if logging.root.getEffectiveLevel() != logging.DEBUG:
            self.print_progress_bar(len(all_predicates), len(all_predicates),
                                    prefix='Processing predicates:', suffix='Complete', length=50)

        # This is for future functionality
        inheritance_query = """
        prefix owl: <http://www.w3.org/2002/07/owl#>
        prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        select ?class ?parent where {
          {
              ?class rdfs:subClassOf+ ?parent .
          }
          UNION
          {
             ?class (owl:equivalentClass|rdfs:subClassOf)/(owl:unionOf|owl:intersectionOf)/rdf:rest*/rdf:first ?parent .
            ?parent a owl:Class
          }
          filter (!isblank(?class) && !isblank(?parent))
        }
        """  # noqa: F841
        # for inheritance_info in self.select_query(inheritance_query):
        #     self.superclasses[inheritance_info['class']].append(inheritance_info['parent'])
        # TODO Coalesce parent and child class references?

        if self.show_shacl:
            self.add_shacl_coloring()

    def record_predicate_usage(self, predicate, predicate_str, usage):
        if usage['src'] not in self.node_data:
            src = {
                'label': usage.get('srcLabel'),
                'links': {},
                'data': {}
            }
            self.node_data[usage['src']] = src
        else:
            src = self.node_data[usage['src']]
        if usage.get('dt'):
            src['data'][(predicate, predicate_str, self.strip_uri(usage['dt']))] = int(usage['num'])
        else:
            if usage['tgt'] not in self.node_data:
                self.node_data[usage['tgt']] = {
                    'label': usage.get('tgtLabel'),
                    'links': {},
                    'data': {}
                }
            src['links'][(predicate, predicate_str, usage['tgt'])] = int(usage['num'])

    def add_shacl_coloring(self):
        shacl_query = """
            prefix sh: <http://www.w3.org/ns/shacl#>

            select distinct ?class ?property where {
              ?shape sh:targetClass ?class .
              { ?shape sh:property/sh:path ?property . }
              UNION
              { ?shape (sh:and|sh:or|sh:xone|sh:not|rdf:first|rdf:rest)+/sh:path ?property }
            }
            """
        shacl_data = self.select_query(shacl_query) if self.repo else self.graph_select_query(shacl_query)
        for row in shacl_data:
            self.shapes[row['class']].append(row['property'])

    def create_predicate_query(self, predicate, predicate_type, limit):
        if predicate_type == str(OWL.ObjectProperty):
            type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>
                prefix skos: <http://www.w3.org/2004/02/skos/core#>

                select ?src ?srcLabel
                       ?tgt ?tgtLabel
                       ?num
                where {
                  {
                    select ?src ?tgt (COUNT(?src) as ?num) where {
                      {
                        select ?src ?tgt where {
                          $pattern
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
        elif predicate_type == str(OWL.DatatypeProperty):
            type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>
                prefix skos: <http://www.w3.org/2004/02/skos/core#>

                select ?src ?srcLabel
                       ?dt
                       ?num
                where {
                  {
                    select ?src ?dt (COUNT(?src) as ?num) where {
                      {
                        select ?src ?dt where {
                          $pattern
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
                prefix skos: <http://www.w3.org/2004/02/skos/core#>

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
                            $pattern
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
                            $pattern
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
        query_text = Template(type_query).substitute(
            pattern=self.filtered_graph_pattern(predicate),
            limit=limit)
        return query_text

    MAX_LINE_WIDTH = 5

    @staticmethod
    def line_width(num_used, graph_max):
        """Scale line width relative to the most commonly occurring edge for the graph"""
        if graph_max == 1:
            return OntoGraf.MAX_LINE_WIDTH
        return min(5, max(1, round(log(num_used, pow(graph_max, 1.0/OntoGraf.MAX_LINE_WIDTH)))))

    def create_instance_graf(self, data_dict=None):
        self.graf = pydot.Dot(graph_type='digraph',
                              label=self.title,
                              labelloc='t',
                              rankdir="LR",
                              ranksep="0.5")

        self.graf.set_node_defaults(**{
            'color': 'lightgray',
            'style': 'unfilled',
            'shape': 'rect',
            'fontname': 'Bitstream Vera Sans',
            'fontsize': '10'
        })
        if data_dict is None:
            data_dict = self.node_data
        logging.debug("Node data: %s", data_dict)
        logging.debug("Shape data: %s", self.shapes)

        # Determine the maximum number any edge occurs in the data, so the edge widths can be properly scaled
        max_common = max(occurs for class_data in data_dict.values() for occurs in class_data['links'].values())

        for class_, class_data in data_dict.items():
            if class_data['data']:
                class_info = \
                    """<<table border="0" cellspacing="0" cellborder="1">
                     <tr>
                      <td align="center" bgcolor="{label_bg}"><font color="{label_fg}">{class_label}</font></td>
                     </tr>
                     <tr>
                      <td align="center">{attribute_text}</td>
                     </tr>
                    </table>>""".format(
                        label_fg="white" if class_ in self.shapes else "black",
                        label_bg="darkgreen" if class_ in self.shapes else "white",
                        class_label=class_data['label'] if class_data['label'] else self.strip_uri(class_),
                        attribute_text="<br/>".join(
                            '<font color="{color}">{prop}: {dt}</font>'.format(
                                color="darkgreen" if predicate in self.shapes[class_] else "black",
                                prop=prop, dt=dt) for predicate, prop, dt in class_data['data'].keys()))
                node = pydot.Node(name='"' + class_ + '"',
                                  margin="0",
                                  label=class_info)
            else:
                node = pydot.Node(name='"' + class_ + '"',
                                  label=class_data['label'] if class_data['label'] else self.strip_uri(class_),
                                  style='filled',
                                  fillcolor="darkgreen" if class_ in self.shapes else "white",
                                  fontcolor="white" if class_ in self.shapes else "black")

            self.graf.add_node(node)

            for link, num in class_data['links'].items():
                predicate, predicate_str, target = link
                edge = pydot.Edge(class_, target,
                                  label=predicate_str,
                                  penwidth=self.line_width(num, max_common),
                                  color=self.shacl_color if predicate in self.shapes[class_] else self.arrow_color,
                                  arrowhead=self.arrowhead)
                self.graf.add_edge(edge)

        self.graf.write(self.outdot)
        if not self.no_image:
            self.graf.write_png(self.outpng)
        logging.debug("Plots saved")

    def ontology_matches_filter(self, ontology):
        if self.include:
            return ontology in self.include
        elif self.exclude:
            return ontology not in self.exclude
        elif self.include_pattern:
            return any(re.search(pattern, ontology) for pattern in self.include_pattern)
        elif self.exclude_pattern:
            return not any(re.search(pattern, ontology) for pattern in self.exclude_pattern)
        else:
            return True

    def filtered_graph_pattern(self, predicate):
        if not self.repo:
            # Local files always go in the default graph
            return f'?s <{predicate}> ?o .'
        elif self.include:
            return f"""
            VALUES ?graph {{{" ".join(f"<{i}>" for i in self.include)}}}
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            """
        elif self.exclude:
            return f"""
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            FILTER (?graph NOT IN ({", ".join(f"<{e}>" for e in self.exclude)}))
            """
        elif self.include_pattern:
            return f"""
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            FILTER ({" || ".join(f"REGEX(STR(?graph), '{i}')" for i in self.include_pattern)})
            """
        elif self.exclude_pattern:
            return f"""
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            FILTER ({" && ".join(f"!REGEX(STR(?graph), '{e}')" for e in self.exclude_pattern)})
            """
        else:
            return f'?s <{predicate}> ?o .'
