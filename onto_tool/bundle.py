"""Implementation of the 'bundle' subcommand."""
import csv
import gzip
import io
import itertools
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from glob import glob
from os.path import basename, isdir, isfile, join, splitext
from typing import List, Tuple

import pyshacl
import yaml
from jsonschema import validate
from pyparsing import ParseException
from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDFS, SKOS, XSD, Namespace
from rdflib.plugins.sparql import prepareQuery
from rdflib.util import guess_format
from SPARQLWrapper import TURTLE

from .mdutils import md2html
from .ontograph import OntoGraf
from .sparql_utils import create_endpoint, select_query_csv
from .utils import parse_rdf, find_single_ontology, perform_export, \
                   add_defined_by

# f-strings are fine in log messages
# pylint: disable=W1203
# CamelCase variable names are fine
# pylint: disable=C0103


class BundleFileException(Exception):
    """Thrown for invalid options in a bundle file not caught by schema."""

    def __init__(self, message, *args):
        super().__init__(message, *args)


class VarDict(dict):
    """Dict that performs variable substitution on values."""

    def __init__(self, *args):
        """Initialize."""
        dict.__init__(self, args)

    def __getitem__(self, k):
        """Interpret raw value as template to be substituted with variables."""
        template = dict.__getitem__(self, k)
        return template.format(**self)


BUNDLE_ACTIONS = {}


def register(name):
    """Register a function as a bundle action"""
    def pass_through(func):
        BUNDLE_ACTIONS[name] = func
        return func
    return pass_through


def replace_patterns_in_file(file, from_pattern, to_string):
    """Replace regex pattern in file contents."""
    with open(file, 'r') as f:
        replaced = re.compile(from_pattern).sub(to_string, f.read())
    with open(file, 'w') as f:
        f.write(replaced)


def __bundle_file_list(action, variables, ignore_target=False):
    """
    Expand a source/target/includes spec into a list of inputFile/outputFile pairs.

    If ignore_target is specified, renaming is ignored and 'outputFile'
    will always be None

    Otherwise, target is assumed to be a directory, which is created if
    it does not exist.

    Parameters
    ----------
    action : dict
        Action definition which contains source, target and (optionally)
        an includes list of patterns.
    variables : dict
        Current variable values to use in substitution.
    ignore_target : bool, optional
        If True, only generate input list.

    Yields
    ------
    dict
        Contains 'inputFile' and 'outputFile' unless ignore_target
        is specified.

    """
    if 'includes' in action or 'excludes' in action:
        # source and target are directories, apply glob
        src_dir = action['source'].format(**variables)
        if not ignore_target:
            tgt_dir = action['target'].format(**variables)
            if not isdir(tgt_dir):
                os.makedirs(tgt_dir)
        else:
            # There are times when
            tgt_dir = None
        include_pattern = action['includes'] if 'includes' in action else '*'
        excluded_files = set()
        if 'excludes' in action:
            excluded_files = set(itertools.chain.from_iterable(
                glob(os.path.join(src_dir, pattern)) for pattern in action['excludes']))
        for pattern in include_pattern:
            matches = list(glob(os.path.join(src_dir, pattern)))
            if not matches and not any(wildcard in pattern for wildcard in '[]*?'):
                logging.warning('%s not found in %s', pattern, src_dir)
            for input_file in (m for m in matches if m not in excluded_files):
                if ignore_target:
                    output_file = None
                else:
                    if 'rename' in action:
                        from_pattern = re.compile(
                            action['rename']['from'].format(**variables))
                        to_pattern = action['rename']['to'].format(**variables)
                        output_file = from_pattern.sub(
                            to_pattern,
                            os.path.basename(input_file))
                    else:
                        output_file = os.path.basename(input_file)
                yield {
                    'inputFile': input_file,
                    'outputFile': None if output_file is None
                    else os.path.join(tgt_dir, output_file)
                }
    else:
        yield {
            'inputFile': action['source'].format(**variables),
            'outputFile': None if ignore_target else action['target'].format(**variables)
        }


def __bundle_transform_shell__(action, arguments, variables):
    for in_out in __bundle_file_list(action, variables):
        invocation_vars = VarDict()
        invocation_vars.update(variables)
        invocation_vars.update(in_out)
        interpreted_args = [arg.format(**invocation_vars) for arg in arguments]
        logging.debug('Running %s', interpreted_args)
        status = subprocess.run(interpreted_args, capture_output=True)
        if status.stdout:
            logging.debug('stdout for %s is %s', action, status.stdout)
        if status.stderr:
            logging.debug('stderr for %s is %s', action, status.stderr)
        if status.returncode != 0:
            logging.error("Tool %s exited with %d: %s",
                          interpreted_args, status.returncode, status.stderr)
            sys.exit(1)
        if 'replace' in action:
            replace_patterns_in_file(in_out['outputFile'],
                                     action['replace']['from'].format(
                                         **invocation_vars),
                                     action['replace']['to'].format(**invocation_vars))


def __bundle_transform_sparql__(action, tool, variables):
    query = tool['query'].format(**variables)
    if isfile(query):
        with open(query, 'r', encoding='utf-8') as qfile:
            query_text = qfile.read()
    else:
        query_text = query

    parsed_query = __parse_update_query__(query_text)

    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        parse_rdf(g, onto_file, rdf_format=rdf_format)

        g.update(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if 'format' in tool:
            rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']

        g.serialize(destination=in_out['outputFile'],
                    format=rdf_format, encoding='utf-8')

        if 'replace' in action:
            replace_patterns_in_file(in_out['outputFile'],
                                     action['replace']['from'].format(
                                         **variables),
                                     action['replace']['to'].format(**variables))


def __parse_update_query__(query_text):
    # Don't need the import cost unless this edge case is hit
    # pylint: disable=C0415
    from rdflib.plugins.sparql.algebra import translateUpdate
    from rdflib.plugins.sparql.parser import parseUpdate
    parsed_query = translateUpdate(parseUpdate(query_text))
    return parsed_query


def __bundle_transform__(action, tools, variables):
    logging.debug('Transform %s', action)
    tool = next((t for t in tools if t['name'] == action['tool']), None)
    if not tool:
        raise BundleFileException('Missing tool ', action['tool'])
    if tool['type'] == 'Java':
        __bundle_transform_shell__(
            action, ["java", "-jar", tool['jar']] + tool['arguments'], variables)
    elif tool['type'] == 'shell':
        __bundle_transform_shell__(action, tool['arguments'], variables)
    elif tool['type'] == 'sparql':
        __bundle_transform_sparql__(action, tool, variables)
    else:
        raise BundleFileException('Unsupported tool type ', tool['type'])


@register(name="definedBy")
def __bundle_defined_by__(action, variables):
    logging.debug('Add definedBy %s', action)
    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        rdf_format = guess_format(onto_file)
        parse_rdf(g, onto_file, rdf_format)

        # locate ontology
        ontology = find_single_ontology(g, onto_file)
        if not ontology:
            logging.warning(f'Ignoring {onto_file}, no ontology found')
            # copy as unchanged
            shutil.copy(in_out['inputFile'], in_out['outputFile'])
        else:
            if not 'mode' in action:
                action['mode'] = 'strict'
            add_defined_by(g, ontology, mode=action['mode'],
                           replace=not __boolean_option__(
                               action, 'retainDefinedBy', variables),
                           versioned=__boolean_option__(action, 'versionedDefinedBy', variables))

            g.serialize(destination=in_out['outputFile'],
                        format=rdf_format, encoding='utf-8')
        if 'replace' in action:
            replace_patterns_in_file(in_out['outputFile'],
                                     action['replace']['from'].format(
                                         **variables),
                                     action['replace']['to'].format(**variables))


@register(name="copy")
def __bundle_copy__(action, variables):
    logging.debug('Copy %s', action)
    for in_out in __bundle_file_list(action, variables):
        if isfile(in_out['inputFile']):
            shutil.copy(in_out['inputFile'], in_out['outputFile'])
            if 'replace' in action:
                replace_patterns_in_file(in_out['outputFile'],
                                         action['replace']['from'].format(
                                             **variables),
                                         action['replace']['to'].format(**variables))
        elif isdir(in_out['inputFile']):
            shutil.copytree(in_out['inputFile'], in_out['outputFile'])


@register(name="move")
def __bundle_move__(action, variables):
    logging.debug('Move %s', action)
    for in_out in __bundle_file_list(action, variables):
        if isfile(in_out['inputFile']):
            shutil.move(in_out['inputFile'], in_out['outputFile'])
            if 'replace' in action:
                replace_patterns_in_file(in_out['outputFile'],
                                         action['replace']['from'].format(
                                             **variables),
                                         action['replace']['to'].format(**variables))
        elif isdir(in_out['inputFile']):
            shutil.move(in_out['inputFile'], in_out['outputFile'])


@register(name="markdown")
def __bundle_markdown__(action, variables):
    logging.debug('Markdown %s', action)
    logging.debug('Markdown %s', action)
    # The default rename is *.md -> *.html
    if 'rename' not in action:
        action['rename'] = {'from': "(.*)\\.md", 'to': "\\g<1>.html"}
    for in_out in __bundle_file_list(action, variables):
        with open(in_out['inputFile']) as md:
            converted_md = md2html(md.read())
        with open(in_out['outputFile'], 'w') as fd:
            converted_md.seek(0)
            shutil.copyfileobj(converted_md, fd, -1)


@register(name="graph")
def __bundle_graph__(action, variables):
    logging.debug('Graph %s', action)
    documentation = action['target'].format(**variables)
    version = action['version'].format(**variables)
    title = action['title'].format(**variables)
    if not isdir(documentation):
        os.mkdir(documentation)
    compact = action['compact'] if 'compact' in action else False
    og = OntoGraf([f['inputFile'] for f in __bundle_file_list(action, variables)],
                  outpath=documentation, wee=[] if compact else None, title=title, version=version)
    og.gather_schema_info_from_files()
    og.create_schema_graf()


def __bundle_local_sparql_each__(action, variables, queries):
    for in_out in __bundle_file_list(action, variables):
        g = Graph()
        onto_file = in_out['inputFile']
        parse_rdf(g, onto_file)
        logging.debug("Input graph size for %s is %d",
                      in_out['inputFile'], len(g))

        updated = False
        for query_file, query_text in queries:
            logging.debug("Applying %s to %s", query_file, in_out['inputFile'])
            parsed_update = None
            parsed_query = None
            try:
                parsed_update = __parse_update_query__(query_text)
            except ParseException:
                # Not a update
                parsed_query = prepareQuery(query_text)

            if parsed_update:
                g.update(parsed_update)
                __transfer_query_prefixes__(g, parsed_update)
                updated = True
            else:
                results = g.query(
                    parsed_query,
                    initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

                if results.vars is not None:
                    # SELECT Query
                    select_output = __determine_output_file_name__(in_out['outputFile'],
                                                                   queries, query_file,
                                                                   suffix='csv')
                    with open(select_output, 'w', encoding='utf-8') as csv_file:
                        __serialize_select_results__(csv_file, results)

                elif results.graph is not None:
                    # CONSTRUCT Query
                    __transfer_query_prefixes__(results.graph, parsed_query)
                    rdf_format, suffix = __determine_format_and_suffix(action)
                    construct_output = __determine_output_file_name__(in_out['outputFile'],
                                                                      queries, query_file,
                                                                      suffix=suffix)
                    results.graph.serialize(
                        destination=construct_output, format=rdf_format, encoding='utf-8')
                else:
                    raise BundleFileException(
                        'Unknown query type: ' + query_text)

        if updated:
            if 'format' in action:
                rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
            else:
                rdf_format = 'turtle'
            logging.debug("Saving updated RDF to %s", in_out['outputFile'])
            g.serialize(destination=in_out['outputFile'],
                        format=rdf_format, encoding='utf-8')


def __bundle_local_sparql__(action, variables, output, queries):
    g = __build_graph_from_inputs__(action, variables)
    updated = False
    for query_file, query_text in queries:
        parsed_update = None
        parsed_query = None
        try:
            parsed_update = __parse_update_query__(query_text)
        except ParseException:
            # Not a update
            parsed_query = prepareQuery(query_text)

        if parsed_update:
            g.update(parsed_update)
            __transfer_query_prefixes__(g, parsed_update)
            updated = True
        else:
            results = g.query(
                parsed_query,
                initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

            if results.vars is not None:
                # SELECT Query
                select_output = __determine_output_file_name__(
                    output, queries, query_file, suffix='csv')
                with open(select_output, 'w', encoding='utf-8') as csv_file:
                    __serialize_select_results__(csv_file, results)

            elif results.graph is not None:
                # CONSTRUCT Query
                __transfer_query_prefixes__(results.graph, parsed_query)
                rdf_format, suffix = __determine_format_and_suffix(action)
                construct_output = __determine_output_file_name__(
                    output, queries, query_file, suffix=suffix)
                results.graph.serialize(
                    destination=construct_output, format=rdf_format, encoding='utf-8')
            else:
                raise BundleFileException('Unknown query type: ' + query_text)

    if updated:
        if 'format' in action:
            rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
        else:
            rdf_format = 'turtle'
        g.serialize(destination=output, format=rdf_format, encoding='utf-8')


def __transfer_query_prefixes__(g, parsed_update):
    if isinstance(parsed_update, list):
        for update in parsed_update:
            for prefix, uri in update.prologue.namespace_manager.namespaces():
                g.bind(prefix, uri)
    else:
        for prefix, uri in parsed_update.prologue.namespace_manager.namespaces():
            g.bind(prefix, uri)


def __determine_format_and_suffix(action: dict) -> tuple:
    if 'format' in action:
        rdf_format = 'pretty-xml' if action['format'] == 'xml' else action['format']
    else:
        rdf_format = 'turtle'
    suffix = 'ttl' if 'format' not in action or action['format'] == 'turtle' else action['format']
    return rdf_format, suffix


def __determine_output_file_name__(output, queries, query_file, suffix):
    if len(queries) == 1:
        select_output = output
    else:
        base, _ = splitext(basename(query_file))
        select_output = os.path.join(output, f'{base}.{suffix}')
    return select_output


def __bundle_endpoint_sparql__(action, variables, output, queries):
    for query_file, query_text in queries:
        parsed_update = None
        parsed_query = None
        try:
            parsed_update = __parse_update_query__(query_text)
        except ParseException:
            # Not a update
            parsed_query = prepareQuery(query_text)

        # parsed_query.algebra.name will be SelectQuery, ConstructQuery or AskQuery
        if parsed_update:
            __endpoint_update_query__(
                action['endpoint'], variables, query_text)
        else:
            if parsed_query.algebra.name == 'SelectQuery':
                select_output = __determine_output_file_name__(
                    output, queries, query_file, suffix='csv')
                with open(select_output, 'wb') as csv_file:
                    csv_file.write(__endpoint_select_query__(
                        action['endpoint'], variables, query_text))
            elif parsed_query.algebra.name == 'ConstructQuery':
                results = __endpoint_construct_query__(
                    action['endpoint'], variables, query_text)
                rdf_format, suffix = __determine_format_and_suffix(action)
                __transfer_query_prefixes__(results, parsed_query)
                construct_output = __determine_output_file_name__(
                    output, queries, query_file, suffix=suffix)
                results.serialize(destination=construct_output,
                                  format=rdf_format, encoding='utf-8')
            else:
                raise BundleFileException('Unknown query type: ' + query_text)


@register(name="sparql")
def __bundle_sparql__(action, variables):
    logging.debug('SPARQL %s', action)
    output = action['target'].format(
        **variables) if 'target' in action else None
    queries = __build_query_list__(action, variables)

    if 'endpoint' in action:
        __bundle_endpoint_sparql__(action, variables, output, queries)
    else:
        if 'eachFile' in action and action['eachFile']:
            __bundle_local_sparql_each__(action, variables, queries)
        else:
            __bundle_local_sparql__(action, variables, output, queries)


def __serialize_select_results__(output, results):
    writer = csv.writer(output)
    writer.writerow(results.vars)
    writer.writerows(results)


def __build_graph_from_inputs__(action, variables):
    """Read RDF files specified by source/[inputs] into a Graph"""
    g = Graph()
    for in_out in __bundle_file_list(action, variables, ignore_target=True):
        onto_file = in_out['inputFile']
        parse_rdf(g, onto_file)
    logging.debug("Input graph size is %d", len(g))
    return g


@register(name="verify")
def __bundle_verify__(action, variables):
    logging.debug('Verify %s', action)
    if action['type'] == 'select':
        __verify_select__(action, variables)
    elif action['type'] == 'ask':
        __verify_ask__(action, variables)
    elif action['type'] == 'construct':
        __verify_construct__(action, variables)
    elif action['type'] == 'shacl':
        __verify_shacl__(action, variables)


def __verify_select__(action, variables):
    queries = __build_query_list__(action, variables)

    g = __build_graph_from_inputs__(action, variables)

    fail_count = 0
    stop_on_fail = __boolean_option__(
        action, 'stopOnFail', variables, default=True)
    for query_text in queries:
        logging.debug("Executing SELECT query %s", query_text[0])
        parsed_query = prepareQuery(query_text[1])
        results = g.query(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if results.vars is not None:
            output = [results.vars]
            output.extend(results)
            if (len(output)) > 1:
                fail_count += 1
                serialized = io.StringIO()
                __serialize_select_results__(serialized, results)
                if 'target' in action:
                    if not stop_on_fail:
                        # Treat 'target' as directory.
                        target_dir = action['target'].format(**variables)
                        if not isdir(target_dir):
                            os.mkdir(target_dir)
                        base, _ = splitext(basename(query_text[0]))
                        with open(join(target_dir, base + '.csv'),
                                  'w', encoding='utf-8') as select_output:
                            select_output.write(serialized.getvalue())
                    else:
                        with open(action['target'].format(**variables),
                                  'w', encoding='utf-8') as select_output:
                            select_output.write(serialized.getvalue())
                logging.error("Verification query %s produced non-empty results:\n%s",
                              query_text[0], serialized.getvalue())
                if stop_on_fail:
                    break
        else:
            raise BundleFileException('Invalid query for SELECT verify: ' +
                                      query_text[1] + ', vars is ' + str(results.vars))

    if fail_count > 0:
        sys.exit(1)


def __endpoint_construct_query__(endpoint: dict, variables: dict, query_text: str) -> Graph:
    sparql = create_endpoint(
        endpoint['query_uri'].format(**variables),
        endpoint.get('user').format(**variables),
        endpoint.get('password').format(**variables))

    sparql.setQuery(query_text)
    sparql.setReturnFormat(TURTLE)
    results = sparql.query().convert()
    rg = Graph()
    rg.parse(data=results.decode("utf-8"), format="turtle")
    return rg


def __endpoint_select_query__(endpoint: dict, variables: dict, query_text: str) -> bytes:
    sparql = create_endpoint(
        endpoint['query_uri'].format(**variables),
        endpoint.get('user').format(**variables),
        endpoint.get('password').format(**variables))

    results = select_query_csv(sparql, query_text)
    return results


def __endpoint_update_query__(endpoint: dict, variables: dict, query_text: str):
    uri = endpoint.get('update_uri', endpoint['query_uri'])
    sparql = create_endpoint(
        uri.format(**variables),
        endpoint.get('user').format(**variables),
        endpoint.get('password').format(**variables))

    sparql.setQuery(query_text)
    return sparql.query()


def __verify_construct__(action, variables):
    queries = __build_query_list__(action, variables)

    g = None
    if 'endpoint' not in action:
        g = __build_graph_from_inputs__(action, variables)

    fail_count = 0
    stop_on_fail = __boolean_option__(
        action, 'stopOnFail', variables, default=True)
    fail_on_warning = 'failOn' in action and action['failOn'] == 'warning'
    for query_file, query_text in queries:
        logging.debug("Executing CONSTRUCT query %s", query_file)
        parsed_query = prepareQuery(query_text)
        if 'endpoint' in action:
            results = __endpoint_construct_query__(
                action['endpoint'], variables, query_text)
        else:
            qr = g.query(
                parsed_query,
                initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})
            results = qr.graph

        if results is not None and isinstance(results, Graph):
            # There is no other way to test if a graph is empty
            # pylint: disable=C1802
            if not len(results):
                continue

            for pref, ns in parsed_query.prologue.namespace_manager.namespaces():
                results.bind(pref, ns)
            violation = __process_construct_validation__(output=action.get('target'),
                                                         fail_on_warning=fail_on_warning,
                                                         stop_on_fail=stop_on_fail,
                                                         query_file=query_file,
                                                         graph=results,
                                                         variables=variables)
            if fail_on_warning or violation:
                fail_count += 1
                if stop_on_fail:
                    break
        else:
            raise BundleFileException(
                f'Invalid query for CONSTRUCT verify: {query_text}')

    if fail_count > 0:
        sys.exit(1)


def __process_construct_validation__(output, fail_on_warning, stop_on_fail,
                                     query_file, graph, variables):
    graph.bind("skos", SKOS)
    graph.bind("sh", Namespace('http://www.w3.org/ns/shacl#'))
    serialized, count, violation = __format_validation_results__(graph)
    if not count:
        logging.warning("CONSTRUCT verification %s did not produce well-formed ViolationReport",
                        query_file)
    else:
        if violation or fail_on_warning:
            logging.error("Verification query %s produced non-empty results:\n%s",
                          query_file, serialized)
        else:
            logging.warning("Verification query %s produced non-empty results:\n%s",
                            query_file, serialized)
    if output:
        if not stop_on_fail:
            # Treat 'target' as directory.
            target_dir = output.format(**variables)
            if not isdir(target_dir):
                os.makedirs(target_dir)
            base, _ = splitext(basename(query_file))
            construct_output = join(target_dir, base + '.ttl')
        else:
            construct_output = output.format(**variables)
        graph.serialize(construct_output, format='turtle', encoding='utf-8')
    return violation


def __verify_shacl__(action, variables):
    data_graph = __build_graph_from_inputs__(action, variables)
    shape_graph = __build_graph_from_inputs__(action['shapes'], variables)

    logging.debug("Data graph has %s triples", sum(1 for _ in data_graph))
    logging.debug("Shape graph has %s triples", sum(1 for _ in shape_graph))

    conforms, results_graph, _ = \
        pyshacl.validate(
            data_graph, shacl_graph=shape_graph,
            inference=None if 'inference' not in action else action['inference'],
            abort_on_first=False, meta_shacl=False,
            advanced=True, js=False, debug=False)

    logging.debug("Post-inference data graph has %s triples",
                  sum(1 for _ in data_graph))

    if not conforms:
        if 'target' in action:
            results_graph.serialize(
                destination=action['target'].format(**variables),
                format='turtle', encoding='utf-8')
        result_table, count, violation = __format_validation_results__(
            results_graph)
        fail_on_warning = 'failOn' in action and action['failOn'] == 'warning'
        if not count:
            logging.warning(
                "SHACL verification did not produce a well-formed ViolationReport:\n%s",
                result_table)
        else:
            if violation or fail_on_warning:
                logging.error(
                    "SHACL verification produced non-empty results:\n%s", result_table)
            else:
                logging.warning(
                    "SHACL verification produced non-empty results:\n%s", result_table)
        if fail_on_warning or violation:
            sys.exit(1)


def __format_validation_results__(results_graph: Graph) -> Tuple[str, int, bool]:
    """Format validation results as text table.

    Adjusts the width of the table so that every row fits
    """
    result_table = io.StringIO()
    violations = results_graph.query("""
            prefix sh: <http://www.w3.org/ns/shacl#>
            SELECT ?focus ?path ?value ?component ?severity ?message WHERE {
                ?violation
                   sh:focusNode ?focus ;
                   sh:resultMessage ?message ;
                   sh:resultSeverity ?severity .
                OPTIONAL { ?violation sh:value ?value }
                OPTIONAL { ?violation sh:resultPath ?path }
                OPTIONAL { ?violation sh:sourceConstraintComponent ?component }
            }
        """)
    rows = []
    headers = ['Focus', 'Path', 'Value', 'Severity', 'Message']
    max_length = [len(h) for h in headers]

    def format_value(v):
        """Format RDF element as string."""
        if v is None:
            return ''
        if isinstance(v, Literal):
            return str(v)
        return v.n3(results_graph.namespace_manager)

    violation_seen = False
    for row in violations:
        message = str(row.message)
        if len(message) > 50:
            message = message[0:47] + '...'
        severity = row.severity.n3(results_graph.namespace_manager)
        violation_seen |= severity == 'sh:Violation'
        as_text = [
            row.focus.n3(results_graph.namespace_manager),
            format_value(row.path if row.path else row.component),
            format_value(row.value),
            severity,
            message
        ]
        # Extend the width of each column to contain the longest value.
        max_length = [max(a, b) for a, b in zip(
            max_length, [len(s) for s in as_text])]
        rows.append(as_text)
    row_format = " ".join(
        f"{{:{length}.{length}}}" for length in max_length) + "\n"
    rows.sort(key=lambda x: x[0])
    result_table.write(row_format.format(*headers))
    for row in rows:
        result_table.write(row_format.format(*row))
    return result_table.getvalue(), len(rows), violation_seen


def __verify_ask__(action, variables):
    queries = __build_query_list__(action, variables)

    g = __build_graph_from_inputs__(action, variables)

    fail_count = 0
    stop_on_fail = __boolean_option__(
        action, 'stopOnFail', variables, default=True)
    for query_text in queries:
        parsed_query = prepareQuery(query_text[1])
        results = g.query(
            parsed_query,
            initNs={'xsd': XSD, 'owl': OWL, 'rdfs': RDFS, 'skos': SKOS})

        if results.askAnswer is not None:
            if results.askAnswer != action['expected']:
                fail_count += 1
                logging.error(
                    "Verification ASK query %s did not match expected result %s",
                    query_text[0], action['expected'])
                if stop_on_fail:
                    break
        else:
            raise BundleFileException(
                f'Invalid query for ASK verify: {query_text}')

    if fail_count > 0:
        sys.exit(1)


def __build_query_list__(action: dict, variables: dict) -> List[Tuple]:
    """Expands the query specification into list of (file name, query text) tuples."""

    def read_query_file(query):
        with open(query, 'r', encoding='utf-8') as q_file:
            q_text = q_file.read()
        return q_text

    if 'query' in action:
        query = action['query'].format(**variables)
        if isfile(query):
            q_text = read_query_file(query)
            queries = [(query, q_text)]
        else:
            queries = [('inline', query)]
    elif 'queries' in action:
        query_files = [
            entry['inputFile'] for entry in
            __bundle_file_list(action['queries'], variables, ignore_target=True)]
        queries = [(query, read_query_file(query)) for query in query_files]
    else:
        raise BundleFileException(
            'No queries specified for verify action: ' + str(action))
    return queries


def __boolean_option__(action, key, variables, default=False):
    if key not in action:
        return default
    value = action[key]
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value.format(**variables)).lower() in ("yes", "true", "t", "1")


@register(name="export")
def __bundle_export__(action, variables):
    logging.debug('Export %s', action)
    output = __create_output(
        __boolean_option__(action, 'compress', variables),
        action['target'].format(**variables))

    o_format = action['format'].format(
        **variables) if 'format' in action else 'turtle'
    o_format = 'pretty-xml' if o_format == 'xml' else o_format

    context = action['context'].format(
        **variables) if 'context' in action else None

    merge = None
    if 'merge' in action:
        merge = (action['merge']['iri'], action['merge']['version'])

    paths = list(f['inputFile']
                 for f in __bundle_file_list(action, variables, ignore_target=True))

    defined_by = None
    if 'definedBy' in action:
        defined_by = action['definedBy'].format(**variables)

    perform_export(output, o_format,
                   paths,
                   context,
                   __boolean_option__(action, 'stripVersions', variables),
                   merge,
                   defined_by,
                   __boolean_option__(
                       action, 'retainDefinedBy', variables),
                   __boolean_option__(action, 'versionedDefinedBy', variables))

    output.close()


def __create_output(compressed, filename):
    if compressed:
        return gzip.open(filename, 'wt', encoding="utf-8")

    return open(filename, 'w', encoding="utf-8")


def bundle_ontology(command_line_variables, bundle_path):
    """
    Bundle ontology and related artifacts for release.

    Parameters
    ----------
    command_line_variables : list
        list of variable values to substitute into the template.
    bundle_path : string
        Path to YAML or JSON bundle definition.

    Returns
    -------
    None.

    """
    extension = os.path.splitext(bundle_path)[1]
    schema_file = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        'bundle_schema.yaml')
    with open(bundle_path, 'r', encoding="utf-8") as b_stream, \
            open(schema_file, 'r', encoding="utf-8") as schema:
        if extension == '.yaml':
            bundle = yaml.safe_load(b_stream)
        else:
            # assume json regardless of extension
            bundle = json.load(b_stream)

        # will throw ValidationError on failure
        validate(bundle, yaml.safe_load(schema))

    variables = VarDict()
    variables.update(bundle['variables'])
    variables.update(dict((n, v) for n, v in command_line_variables))
    substituted = dict((k, variables[k]) for k in variables)

    for action in bundle['actions']:
        if 'message' in action:
            logging.info(action['message'].format(**substituted))
        if action['action'] == 'transform':
            __bundle_transform__(action, bundle['tools'], substituted)
        elif action['action'] == 'mkdir':
            path = action['directory'].format(**substituted)
            if not isdir(path):
                os.makedirs(path)
        elif action['action'] in BUNDLE_ACTIONS:
            BUNDLE_ACTIONS[action['action']](action, substituted)
        else:
            raise BundleFileException('Unknown action ' + str(action))
