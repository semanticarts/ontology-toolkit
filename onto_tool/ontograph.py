"""
Generates a graphical representation of a collection of ontologies.

It extracts the classes, object properties, data properties (if any),
and entities of subClass "owl:Thing". It establishes the imports for each file,
and then presents the results as a graphviz 'dot' file and a .png file.
@version 2
"""

import datetime
import json
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
from rdflib import BNode, Graph
from rdflib.namespace import OWL, RDF
from rdflib.util import guess_format

from .sparql_utils import create_endpoint, select_query

# Ignore \l - uses them as a line separator
# pylint: disable=W1401


class OntoGraf:
    """Generates schema or instance graphs."""

    def __init__(self, files, repo=None, **kwargs):
        self.wee = kwargs.get('wee', None)
        self.hide = kwargs.get('hide')
        title = kwargs.get('title')
        version = kwargs.get('version')
        if not version:
            version = datetime.datetime.now().isoformat()[:10]

        out_filename = self.__configure_data_source(
            repo, kwargs, title, version)
        self.graf = None
        self.files = files
        self.repo = repo
        self.data = None
        self.no_image = kwargs.get('no_image', False)
        self.single_graph = kwargs.get('single_graph', False)
        self.concentrate_links = kwargs.get('concentrate_links')

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

        # Data structures for instance data gather
        self.node_data, self.class_names, self.class_counts, self.inheritance = \
            {}, {}, defaultdict(int), []

        # Default color configuration
        self.super_color = "blue"
        self.arrow_color = "darkorange2"
        self.shacl_color = "darkgreen"
        self.arrowhead = "vee"

        self.label_lang = kwargs.get('label_language', 'en')

        self.include = kwargs.get('include')
        self.exclude = kwargs.get('exclude')
        self.include_pattern = kwargs.get('include_pattern')
        self.exclude_pattern = kwargs.get('exclude_pattern')

        self.superclasses = defaultdict(set)

        self.show_shacl = kwargs.get('show_shacl')
        self.shapes = defaultdict(list)
        self.show_bnode_subjects = kwargs.get('show_bnode_subjects')

    def __configure_data_source(self, repo, kwargs, title, version):
        """Determine graph title and output location from data source."""
        self.cached_data = {}
        if kwargs.get('cache'):
            self.cache = json.load(kwargs['cache'])
            self.save_cache = None  # duplicative
        else:
            self.cache = None
            self.save_cache = kwargs.get('save_cache')

        if self.cache:
            self.title = self.cache['title']
            out_filename = self.cache['out_filename']
        elif repo:
            anonymized, repo_base = self.__anonymize_url(repo)
            self.title = (title or anonymized) + ': ' + version
            out_filename = repo_base
            self.cached_data['title'] = 'Cached ' + self.title
            self.cached_data['out_filename'] = 'cached_' + out_filename
        else:
            self.title = f'{title or "Gist"} Ontology: {version}'
            out_filename = f'{title or "Gist"}{version}'
        return out_filename

    @staticmethod
    def __anonymize_url(url):
        """Remove username and password from URI, if present."""
        parsed = urlparse(url)
        anonymized = urlunparse((parsed.scheme,
                                 re.sub('^.*@', '', parsed.netloc),
                                 parsed.path,
                                 '', '', ''))
        return anonymized, os.path.basename(parsed.path)

    def __remote_select_query(self, query):
        """Execute SPARQL SELECT query, return results as generator."""
        logging.debug(f"Query against {self.repo}")
        logging.debug(f"Query\n {query}")

        sparql = create_endpoint(self.repo)
        return select_query(sparql, query)

    def __local_select_query(self, query):
        """Execute SPARQL SELECT query on local data, return results as generator."""
        logging.debug(f"Local Query\n {query}")
        if not self.data:
            self.data = Graph()
            for file_path in self.files:
                filename = os.path.basename(file_path)
                logging.debug('Parsing %s for documentation', filename)
                self.data.parse(file_path, format=guess_format(file_path))

        results = self.data.query(query)
        for result in results:
            yield dict((str(k), str(v) if v is not None else None)
                       for k, v in zip(results.vars, result))

    def __select_query(self, query: str, cache_id: str):
        if self.cache:
            return self.cache[cache_id]
        if self.repo:
            data = list(self.__remote_select_query(query))
            self.cached_data[cache_id] = data
            return data
        return list(self.__local_select_query(query))

    @staticmethod
    def __strip_uri(uri):
        stripped = re.sub(r'^.*[/#](.*?)(X.x.x|\d+.\d+.\d+)?$', '\\1',
                          re.sub(r'[#/]$', '', str(uri)))
        if not stripped:
            logging.warning("Stripping %s went horribly wrong", uri)
            return uri
        return stripped

    def gather_schema_info_from_files(self):
        """Load schema data from local ontology."""
        self.node_data = {}
        for file_path in self.files:
            filename = os.path.basename(file_path)
            logging.debug('Parsing %s for documentation', filename)
            graph = Graph()
            graph.parse(file_path, format=guess_format(file_path))

            ontology = next(graph.subjects(RDF.type, OWL.Ontology))
            ontology_name = self.__strip_uri(ontology)
            classes = [self.__strip_uri(c) for c in graph.subjects(RDF.type, OWL.Class)
                       if not isinstance(c, BNode) or self.show_bnode_subjects]
            obj_props = [self.__strip_uri(c)
                         for c in graph.subjects(RDF.type, OWL.ObjectProperty)]
            data_props = [self.__strip_uri(c)
                          for c in graph.subjects(RDF.type, OWL.DatatypeProperty)]
            annotation_props = [self.__strip_uri(c)
                                for c in graph.subjects(RDF.type, OWL.AnnotationProperty)]
            all_seen = set(classes + obj_props + data_props + annotation_props)
            gist_things = [
                self.__strip_uri(s) for (s, o) in graph.subject_objects(RDF.type)
                if (not isinstance(s, BNode) or self.show_bnode_subjects) and
                not s == ontology and not self.__strip_uri(s) in all_seen]
            imports = [self.__strip_uri(c)
                       for c in graph.objects(ontology, OWL.imports)]

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
        """Load schema data from SPARQL endpoint."""
        onto_data = defaultdict(lambda: defaultdict(list))
        bnode_filter = "filter(!ISBLANK(?entity))" if not self.show_bnode_subjects else ""
        if self.single_graph:
            onto_query = """
            prefix owl: <http://www.w3.org/2002/07/owl#>
            prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            prefix xsd: <http://www.w3.org/2001/XMLSchema#>
            prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            prefix gist: <https://ontologies.semanticarts.com/gist/>

            select DISTINCT ?ontology ?entity ?type where {
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
                  $bnode_filter
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

            select DISTINCT ?ontology ?entity ?type where {
              ?ontology a owl:Ontology .
              {
                ?ontology owl:imports ?entity .
                BIND(owl:imports as ?type)
              }
              UNION
              {
                ?entity rdfs:isDefinedBy ?ontology; a ?type .
                ?bnode_filter
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
        for entity in self.__remote_select_query(
                Template(onto_query).substitute(bnode_filter=bnode_filter)):
            key = mapping.get(entity['type'], 'gist_thingsList')
            onto_data[entity['ontology']][key].append(
                self.__strip_uri(entity['entity']))

        if not onto_data:
            logging.warning(
                'Could not find any ontology entities in %s', self.repo)
            return

        self.node_data = defaultdict(dict)
        for ontology, props in onto_data.items():
            self.node_data[ontology]['ontology'] = ontology
            self.node_data[ontology]['ontologyName'] = self.__strip_uri(
                ontology)
            for key in set(mapping.values()).union({'gist_thingsList'}):
                if key != 'imports':
                    self.node_data[ontology][key] = "\\l".join(
                        sorted(set(props[key]))) if key in props else ''
                else:
                    self.node_data[ontology][key] = props[key] if key in props else [
                    ]

    def create_schema_graf(self):
        """Create schema graph from local or remote data."""
        data_dict = self.node_data
        wee = self.wee
        # When 'wee' is not specified at all, it will be None
        # When 'wee' is for all ontologies, it will be an empty list
        # Otherwise, it will contain a list of ontology URI patterns
        if wee is not None and not wee:
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
                if not self.__ontology_matches_filter(ontology):
                    logging.debug("Filtered out %s", ontology)
                    continue
                ontology_name = file_data["ontologyName"]
                render_compact = wee is not None and (
                    not wee or any(re.search(pat, ontology) for pat in wee)
                )
                if render_compact:
                    node = pydot.Node(ontology_name)
                else:
                    ontology_info = "{{{}\\l\\l{}|{}|{}|{}|{}|{}}}".format(
                        file,
                        ontology_name,
                        file_data["classesList"],
                        file_data["obj_propertiesList"],
                        file_data["data_propertiesList"],
                        file_data["annotation_propertiesList"],
                        file_data["gist_thingsList"])
                    node = pydot.Node(ontology_name,
                                      label=ontology_info)

                self.graf.add_node(node)

                for imported in file_data["imports"]:
                    edge = pydot.Edge(ontology_name, imported,
                                      color=self.arrow_color,
                                      arrowhead=self.arrowhead)
                    self.graf.add_edge(edge)
        self.graf.write(self.outdot)
        if not self.no_image:
            self.graf.write(self.outpng, format='png')
        logging.debug("Plots saved")

    class ProgressBar():
        """Renders a progress bar in a terminal.

        Stolen from https://stackoverflow.com/questions/3173320/text-progress-bar-in-the-console
        """

        def __init__(self, total, **kwargs):
            """
            @params:
                total       - Required  : total iterations (Int)
                prefix      - Optional  : prefix string (Str, default='')
                suffix      - Optional  : suffix string (Str, default='')
                decimals    - Optional  : positive number of decimals
                                          in percent complete (Int, default=1)
                length      - Optional  : character length of bar (Int, default=100)
                fill        - Optional  : bar fill character (Str, default='X')
                print_end   - Optional  : end character (e.g. "\r", "\r\n") (Str, default='\r')
            """
            self.total = total
            self.prefix = kwargs.get('prefix', '')
            self.suffix = kwargs.get('suffix', '')
            self.decimals = kwargs.get('decimals', 1)
            self.length = kwargs.get('length', 100)
            self.fill = kwargs.get('fill', 'X')
            self.print_end = kwargs.get('print_end', '\r')

        def print(self, iteration, suffix=None):
            """Call in a loop to create terminal progress bar."""
            # if not sys.stdout.isatty():
            #     return
            if logging.root.getEffectiveLevel() == logging.DEBUG:
                return

            if not suffix:
                suffix = self.suffix
            percent = ("{0:." + str(self.decimals) + "f}").format(100 *
                                                                  (iteration / float(self.total)))
            filled_length = int(self.length * iteration // self.total)
            progress_bar = self.fill * filled_length + \
                '-' * (self.length - filled_length)
            print(
                f'\r{self.prefix} |{progress_bar}| {percent}% {suffix}', end=self.print_end)
            # Print New Line on Complete
            if iteration == self.total:
                print()
            sys.stdout.flush()

    def __hidden(self, uri):
        return any(re.search(pat, uri) for pat in self.hide)

    def __deepest_class(self, class_uris: str):
        _, deepest = max((
            self.inheritance.index(cls_uri) if cls_uri in self.inheritance else -1, cls_uri)
            for cls_uri in class_uris.split(' '))
        return deepest

    def gather_instance_info(self):
        """Gather class and predicate usage from local data or SPARQL endpoint."""
        predicate_query = Template("""
        prefix owl: <http://www.w3.org/2002/07/owl#>
        prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        prefix xsd: <http://www.w3.org/2001/XMLSchema#>
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix gist: <https://ontologies.semanticarts.com/gist/>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>

        select distinct ?predicate ?label ?type where {
          {
            select distinct ?predicate where {
              ?s ?predicate ?o
              FILTER(?predicate NOT IN (
                  rdf:type, rdfs:label, skos:prefLabel,
                  skos:altLabel, skos:definition))
            }
          }
          FILTER (!STRSTARTS(STR(?predicate), 'http://www.w3.org/2002/07/owl#'))
          FILTER (!STRSTARTS(STR(?predicate), 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'))
          FILTER (!STRSTARTS(STR(?predicate), 'http://www.w3.org/2000/01/rdf-schema#'))
          OPTIONAL {
            ?predicate skos:prefLabel|rdfs:label ?label
            FILTER(lang(?label) = '$language' || lang(?label) = '')
          }
          OPTIONAL {
            values ?type { owl:DatatypeProperty owl:ObjectProperty }
            ?predicate a ?type
          }
        }
        """).substitute(language=self.label_lang)
        self.node_data = {}
        all_predicates = self.__select_query(predicate_query, 'all_predicates')

        hidden_predicates = set(predicate['predicate'] for predicate in all_predicates
                                if self.__hidden(predicate['predicate']))
        logging.debug("Hiding predicates: %s", hidden_predicates)
        all_predicates = [
            predicate for predicate in all_predicates
            if predicate['predicate'] not in hidden_predicates]

        if not all_predicates:
            logging.warning('No interesting predicates found in %s',
                            self.repo or ' specified files')
            return

        self.__build_class_hierarchy()

        progress_bar = self.ProgressBar(len(all_predicates),
                                        prefix='Processing predicates:', suffix='', length=50)
        for count, predicate_row in enumerate(all_predicates):
            predicate = predicate_row['predicate']
            predicate_str = predicate_row['label'] if predicate_row.get('label') \
                else self.__strip_uri(predicate)

            progress_bar.print(count,
                               suffix=predicate_str + ' ' * 20)
            pre_time = perf_counter()
            query_text = self.__create_predicate_query(
                predicate, predicate_row.get('type'), self.limit)
            predicate_usage = list(self.__select_query(query_text, predicate))
            logging.debug("%s items returned for %s",
                          len(predicate_usage), predicate)
            for usage in predicate_usage:
                if 'tgt' in usage and usage['tgt'] is None:
                    del usage['tgt']
                if usage.get('src') is None or int(usage.get('num', 0)) < self.threshold:
                    continue
                self.__record_predicate_usage(predicate, predicate_str, usage)

            logging.debug("Fetching %s took %d seconds", str(
                predicate_row), perf_counter() - pre_time)

        progress_bar.print(len(all_predicates), suffix='Complete')

        self.__prune_for_inheritance()

        if self.show_shacl:
            self.__add_shacl_coloring()

        if self.save_cache:
            json.dump(self.cached_data, self.save_cache)

    def __build_class_hierarchy(self):
        bnode_filter = "filter (!isblank(?class) && !isblank(?parent))\n" \
            if not self.show_bnode_subjects else ""
        inheritance_query = Template("""
        prefix owl: <http://www.w3.org/2002/07/owl#>
        prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        prefix skos: <http://www.w3.org/2004/02/skos/core#>

        select distinct ?class ?c_label ?parent ?p_label where {
          {
              ?class rdfs:subClassOf ?parent .
          }
          UNION
          {
             ?class (owl:equivalentClass|rdfs:subClassOf)/
                    (owl:unionOf|owl:intersectionOf)/
                    rdf:rest*/rdf:first ?parent .
            ?parent a owl:Class
          }
          $bnode_filter
          OPTIONAL {
              ?class rdfs:label|skos:prefLabel ?c_label
              FILTER(lang(?c_label) = '$language' || lang(?c_label) = '')
          }
          OPTIONAL {
              ?parent rdfs:label|skos:prefLabel ?p_label
              FILTER(lang(?p_label) = '$language' || lang(?p_label) = '')
          }
        }
        """).substitute(bnode_filter=bnode_filter, language=self.label_lang)
        parents = self.__select_query(inheritance_query, 'parents')

        for inheritance_info in parents:
            self.superclasses[inheritance_info['class']].add(
                inheritance_info['parent'])
            self.class_names[inheritance_info['class']] = \
                inheritance_info.get('c_label') or self.__strip_uri(
                    inheritance_info['class'])
            self.class_names[inheritance_info['parent']] = \
                inheritance_info.get('p_label') or self.__strip_uri(
                    inheritance_info['parent'])

        # Determine evaluation order, root classes to leaves
        remaining_classes = set(self.superclasses.keys())
        root_classes = set(parent for cls, parents in self.superclasses.items()
                           for parent in parents
                           if parent not in remaining_classes)
        eval_order = list(root_classes)
        while remaining_classes:
            next_set = set(cls for cls in remaining_classes
                           if all(parent in eval_order for parent in self.superclasses[cls]))
            # Make superclasses transitive
            for cls in next_set:
                parents = set(self.superclasses[cls])
                for parent in parents:
                    self.superclasses[cls].update(
                        self.superclasses.get(parent, set()))
            eval_order.extend(next_set)
            remaining_classes.difference_update(next_set)

        logging.debug(
            'Inheritance evaluation order:\n%s',
            "\n".join(
                f"\t{self.__strip_uri(cls)}: {list(self.__strip_uri(sup) for sup in self.superclasses[cls])}"
                for cls in eval_order))
        self.inheritance = eval_order

        class_query = self.__create_class_count_query(self.limit)
        class_counts = self.__select_query(class_query, 'class_counts')

        for instance_info in class_counts:
            self.class_counts[self.__deepest_class(
                instance_info['src'])] += int(instance_info['num'])

    def __prune_for_inheritance(self):
        for cls in reversed(self.inheritance):
            if cls not in self.node_data or not self.superclasses[cls]:
                continue
            self.__merge_with_parent(cls, 'links')
            self.__merge_with_parent(cls, 'data')

    def __merge_with_parent(self, cls, link_type):
        removed = []
        for link, count in self.node_data[cls][link_type].items():
            # Locate parents with same link
            parents_with_link = list(
                parent for parent in self.superclasses[cls]
                if parent in self.node_data and link in self.node_data[parent][link_type]
            )
            if not parents_with_link:
                continue
            # Move to the most immediate parent, to create proper superclass chains
            _, max_parent_with_link = max((self.inheritance.index(
                parent), parent) for parent in parents_with_link)
            self.node_data[max_parent_with_link][link_type][link] += count
            self.node_data[cls]['supers'].add(max_parent_with_link)
            removed.append(link)
        for r in removed:
            del self.node_data[cls][link_type][r]

    def __record_predicate_usage(self, predicate, predicate_str, usage):
        src_uri = self.__deepest_class(usage['src'])
        tgt_uri = self.__deepest_class(
            usage['tgt']) if 'tgt' in usage else None
        if self.__hidden(src_uri) or (tgt_uri is not None and self.__hidden(tgt_uri)):
            if tgt_uri is not None:
                logging.debug('Hiding %s to %s link', src_uri, tgt_uri)
            else:
                logging.debug('Hiding %s attribute %s', src_uri, usage['dt'])
            return
        if src_uri not in self.node_data:
            if src_uri is None:
                raise LookupError("None src_uri in " + str(usage))
            src = {
                'label': self.class_names.get(src_uri, self.__strip_uri(src_uri)),
                'links': defaultdict(int),
                'data': defaultdict(int),
                'supers': set()
            }
            self.node_data[src_uri] = src
        else:
            src = self.node_data[src_uri]
        if usage.get('dt'):
            src['data'][(predicate,
                         predicate_str or self.__strip_uri(predicate),
                         self.__strip_uri(usage['dt']))] += int(usage['num'])
        else:
            if tgt_uri not in self.node_data:
                if tgt_uri is None:
                    raise LookupError("None tgt_uri in " + str(usage))
                self.node_data[tgt_uri] = {
                    'label': self.class_names.get(tgt_uri, self.__strip_uri(tgt_uri)),
                    'links': defaultdict(int),
                    'data': defaultdict(int),
                    'supers': set()
                }
            src['links'][(predicate, predicate_str, tgt_uri)
                         ] += int(usage['num'])

    def __add_shacl_coloring(self):
        shacl_query = """
            prefix sh: <http://www.w3.org/ns/shacl#>

            select distinct ?class ?property where {
              ?shape sh:targetClass ?class .
              { ?shape sh:property/sh:path ?property . }
              UNION
              { ?shape (sh:and|sh:or|sh:xone|sh:not|rdf:first|rdf:rest)+/sh:path ?property }
            }
            """
        shacl_data = self.__select_query(shacl_query, 'shacl')
        for row in shacl_data:
            self.shapes[row['class']].append(row['property'])

    def __create_class_count_query(self, limit):
        bnode_filter = "FILTER(!ISBLANK(?s))" if not self.show_bnode_subjects else ""
        class_query = """
            prefix owl: <http://www.w3.org/2002/07/owl#>
            prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            prefix xsd: <http://www.w3.org/2001/XMLSchema#>
            prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            prefix gist: <https://ontologies.semanticarts.com/gist/>
            prefix skos: <http://www.w3.org/2004/02/skos/core#>

            select ?src (COUNT(?src) as ?num) where {
              {
                select (group_concat(?o;separator=' ') as ?src) where {
                  $pattern
                  $bnode_filter
                  FILTER (!STRSTARTS(STR(?o), 'http://www.w3.org/2002/07/owl#'))
                } group by ?s LIMIT $limit
              }
            } group by ?src
            """
        query_text = Template(class_query).substitute(
            pattern=self.__filtered_graph_pattern(str(RDF.type)),
            bnode_filter=bnode_filter,
            limit=limit)
        return query_text

    def __create_predicate_query(self, predicate, predicate_type, limit):
        bnode_filter = "FILTER(!ISBLANK(?s))" if not self.show_bnode_subjects else ""
        if predicate_type == str(OWL.ObjectProperty):
            type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>
                prefix skos: <http://www.w3.org/2004/02/skos/core#>

                select ?src ?tgt (COUNT(?src) as ?num) where {
                  {
                    select
                        (group_concat(?src_c;separator=' ') as ?src)
                        (group_concat(?tgt_c;separator=' ') as ?tgt)
                    where {
                      $pattern
                      $bnode_filter
                      ?s a ?src_c .
                      FILTER (!STRSTARTS(STR(?src_c), 'http://www.w3.org/2002/07/owl#'))
                      ?o a ?tgt_c .
                    } group by ?s ?o LIMIT $limit
                  }
                } group by ?src ?tgt
                """
        elif predicate_type == str(OWL.DatatypeProperty):
            type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>
                prefix skos: <http://www.w3.org/2004/02/skos/core#>

                select ?src ?dt (COUNT(?src) as ?num) where {
                  {
                    select (group_concat(?src_c;separator=' ') as ?src) (SAMPLE(COALESCE(?dtype, xsd:string)) as ?dt) where {
                      $pattern
                      FILTER(ISLITERAL(?o))
                      $bnode_filter
                      ?s a ?src_c .
                      FILTER (!STRSTARTS(STR(?src_c), 'http://www.w3.org/2002/07/owl#'))
                      BIND(DATATYPE(?o) as ?dtype) .
                    } group by ?s LIMIT $limit
                  }
                } group by ?src ?dt
                """
        else:
            type_query = """
                prefix owl: <http://www.w3.org/2002/07/owl#>
                prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                prefix xsd: <http://www.w3.org/2001/XMLSchema#>
                prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                prefix gist: <https://ontologies.semanticarts.com/gist/>
                prefix skos: <http://www.w3.org/2004/02/skos/core#>

                select ?src
                       ?tgt
                       ?dt
                       ?num
                where {
                  {
                    {
                      select ?src ?tgt (COUNT(?src) as ?num) where {
                        {
                            select (group_concat(?src_c;separator=' ') as ?src)
                                   (group_concat(?tgt_c;separator=' ') as ?tgt) where {
                              $pattern
                              $bnode_filter
                              ?s a ?src_c .
                              FILTER (!STRSTARTS(STR(?src_c), 'http://www.w3.org/2002/07/owl#'))
                              FILTER (!STRSTARTS(STR(?src_c), 'http://www.w3.org/ns/shacl#'))
                              ?o a ?tgt_c .
                            } group by ?s ?o LIMIT $limit
                        }
                      } group by ?src ?tgt
                    }
                  }
                  UNION
                  {
                    {
                      select ?src ?dt (COUNT(?src) as ?num) where {
                        {
                            select (group_concat(?src_c;separator=' ') as ?src)
                                   (SAMPLE(COALESCE(?dtype, xsd:string)) as ?dt) where {
                              $pattern
                              FILTER(ISLITERAL(?o))
                              $bnode_filter
                              ?s a ?src_c .
                              FILTER (!STRSTARTS(STR(?src_c), 'http://www.w3.org/2002/07/owl#'))
                              FILTER (!STRSTARTS(STR(?src_c), 'http://www.w3.org/ns/shacl#'))
                              BIND(DATATYPE(?o) as ?dtype) .
                            } group by ?s LIMIT $limit
                        }
                      } group by ?src ?dt
                    }
                  }
                }
                """
        query_text = Template(type_query).substitute(
            pattern=self.__filtered_graph_pattern(predicate),
            bnode_filter=bnode_filter,
            limit=limit)
        return query_text

    MIN_LINE_WIDTH = 1
    MAX_LINE_WIDTH = 5

    @staticmethod
    def __line_width(num_used, graph_max):
        """Scale line width relative to the most commonly occurring edge for the graph"""
        if graph_max == 1:
            return OntoGraf.MAX_LINE_WIDTH
        if num_used == 0:
            return OntoGraf.MIN_LINE_WIDTH
        try:
            return min(OntoGraf.MAX_LINE_WIDTH,
                       max(OntoGraf.MIN_LINE_WIDTH,
                           round(log(num_used, pow(graph_max, 1.0 / OntoGraf.MAX_LINE_WIDTH)))))
        except ValueError:
            logging.warning(
                'Failed to determine line width from num=%d max=%d', num_used, graph_max)
            return OntoGraf.MIN_LINE_WIDTH

    MAX_FONT_SIZE = 24
    MIN_FONT_SIZE = 14

    @staticmethod
    def __font_size(num_instances, graph_max):
        """Scale line width relative to the most commonly occurring edge for the graph"""
        if num_instances == 0 or graph_max == 1:
            return OntoGraf.MIN_FONT_SIZE
        span = OntoGraf.MAX_FONT_SIZE - OntoGraf.MIN_FONT_SIZE
        try:
            return OntoGraf.MIN_FONT_SIZE - 1 + \
                min(span, max(1, round(log(num_instances, pow(graph_max, 1.0 / span)))))
        except ValueError:
            logging.warning(
                'Failed to determine font size from num=%d max=%d', num_instances, graph_max)
            return OntoGraf.MIN_FONT_SIZE

    def create_instance_graf(self, data_dict=None):
        """Create graph from gathered instance data."""
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

        if not data_dict:
            logging.warning("No data found with the specified parameters.")
            return

        # Determine the maximum number any edge occurs in the data,
        # so the edge widths can be properly scaled
        common_list = [
            occurs for class_data in data_dict.values()
            for occurs in class_data['links'].values()
        ]
        max_common = 0 if len(common_list) == 0 else max(common_list)

        max_instance = max(self.class_counts.values())

        for class_, class_data in data_dict.items():
            node = self.__create_instance_graph_node(
                max_instance, class_, class_data)

            self.graf.add_node(node)

            by_predicate, compacted_links = self.__determine_compacted_links(
                class_, class_data)

            for link, num in class_data['links'].items():
                predicate, predicate_str, target = link
                if predicate in compacted_links and target != class_:
                    continue
                edge = pydot.Edge(class_, target,
                                  label=predicate_str,
                                  penwidth=self.__line_width(num, max_common),
                                  color=self.shacl_color if predicate in self.shapes[
                                      class_] else self.arrow_color,
                                  arrowhead=self.arrowhead)
                self.graf.add_edge(edge)

            for predicate in compacted_links:
                self.add_compacted_edges(
                    max_common, class_, predicate, class_data, by_predicate[predicate])

            for super_class in class_data['supers']:
                edge = pydot.Edge(class_, super_class,
                                  penwidth=1,
                                  color=self.super_color,
                                  arrowhead='normal')
                self.graf.add_edge(edge)

        self.graf.write(self.outdot, encoding="utf-8")
        if not self.no_image:
            self.graf.write(self.outpng, format='png')
        logging.debug("Plots saved")

    def add_compacted_edges(self, max_common: int, source_class: str, predicate: str,
                            class_data: dict, links: dict):
        """Add graph edges for compacted links.

        For a class that is linked to many classes via the same predicate,
        generate a single labeled edge to a 'point' intermediate node, then
        add unlabeled edges from the itermediate node to the target nodes.
        This makes the diagram less crowded and clearer.
        """
        shared_node_id = source_class + '_' + predicate
        shared_node = pydot.Node(
            name='"' + shared_node_id + '"', shape='point', color="black")
        self.graf.add_node(shared_node)
        total_count = sum(class_data['links'][link] for link in links)
        edge_color = self.shacl_color if predicate in self.shapes[
            source_class] else self.arrow_color
        predicate_label = next(link for link in links)[1]
        self.graf.add_edge(
            pydot.Edge(source_class, shared_node_id,
                       label=predicate_label,
                       penwidth=self.__line_width(total_count, max_common), color=edge_color))
        for link in links:
            _, _, target = link
            edge = pydot.Edge(shared_node_id, target,
                              penwidth=self.__line_width(
                                  class_data['links'][link], max_common),
                              color=edge_color,
                              arrowhead=self.arrowhead)
            self.graf.add_edge(edge)

    def __determine_compacted_links(self, class_, class_data):
        by_predicate = defaultdict(set)
        if self.concentrate_links != 0:
            for link in class_data['links']:
                predicate, _, target = link
                # Don't concentrate self-links
                if class_ != target:
                    by_predicate[predicate].add(link)

        compacted_links = set(predicate for predicate, links in by_predicate.items()
                              if len(links) >= self.concentrate_links)

        return by_predicate, compacted_links

    def __create_instance_graph_node(self, max_instance, class_, class_data):
        # Using .format is more readable here
        # pylint: disable=C0209

        node_font_size = self.__font_size(
            self.class_counts[class_], max_instance)
        node_line_width = self.__line_width(
            self.class_counts[class_], max_instance)
        class_label = class_data['label'] if class_data['label'] else self.__strip_uri(class_)

        if class_data['data']:
            formatted_label = '<font point-size="{fontsize}" color="{label_fg}">{class_label}</font>'.format(
                label_fg="white" if class_ in self.shapes else "black",
                fontsize=node_font_size,
                class_label=class_label
            )
            class_info = \
                """<<table color="black" border="{line_width}" cellspacing="0" cellborder="1">
                    <tr>
                    <td align="center" bgcolor="{label_bg}">{formatted_label}</td></tr>
                    <tr>
                    <td align="center">{attribute_text}</td>
                    </tr>
                </table>>""".format(
                    label_bg="darkgreen" if class_ in self.shapes else "white",
                    formatted_label=formatted_label,
                    line_width=node_line_width,
                    attribute_text="<br/>".join(
                        '<font point-size="{fontsize}" color="{color}">{prop}: {dt}</font>'.format(
                            color="darkgreen" if predicate in self.shapes[class_] else "black",
                            fontsize=round(node_font_size * 2 / 3),
                            prop=prop, dt=dt) for predicate, prop, dt in class_data['data'].keys()))
            node = pydot.Node(name='"' + class_ + '"',
                              margin="0",
                              label=class_info)
        else:
            node = pydot.Node(name='"' + class_ + '"',
                              label=class_label,
                              style='filled',
                              fontsize=node_font_size,
                              penwidth=node_line_width,
                              color="black",
                              fillcolor="darkgreen" if class_ in self.shapes else "white",
                              fontcolor="white" if class_ in self.shapes else "black")

        return node

    def __ontology_matches_filter(self, ontology):
        if self.include:
            return ontology in self.include
        if self.exclude:
            return ontology not in self.exclude
        if self.include_pattern:
            return any(re.search(pattern, ontology) for pattern in self.include_pattern)
        if self.exclude_pattern:
            return not any(re.search(pattern, ontology) for pattern in self.exclude_pattern)
        return True

    def __filtered_graph_pattern(self, predicate):
        if not self.repo:
            # Local files always go in the default graph
            return f'?s <{predicate}> ?o .'
        if self.include:
            return f"""
            VALUES ?graph {{{" ".join(f"<{i}>" for i in self.include)}}}
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            """
        if self.exclude:
            return f"""
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            FILTER (?graph NOT IN ({", ".join(f"<{e}>" for e in self.exclude)}))
            """
        if self.include_pattern:
            return f"""
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            FILTER ({" || ".join(f"REGEX(STR(?graph), '{i}')" for i in self.include_pattern)})
            """
        if self.exclude_pattern:
            return f"""
            GRAPH ?graph {{
                ?s <{predicate}> ?o .
            }}
            FILTER ({" && ".join(f"!REGEX(STR(?graph), '{e}')" for e in self.exclude_pattern)})
            """
        return f'?s <{predicate}> ?o .'
