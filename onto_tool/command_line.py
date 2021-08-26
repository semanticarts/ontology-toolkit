import argparse
import os
import re
import sys
from urllib.parse import urlparse
from rdflib import URIRef


def _uri_validator(x):
    """Check for valid URI."""
    try:
        result = urlparse(x)
        return all([result.scheme, any([result.netloc, result.path])])
    except ValueError:
        return False


class UriValidator(argparse.Action):
    """Validates IRI argument."""

    # No public method needed
    # pylint: disable=R0903
    def __call__(self, parser, namespace, values, option_string=None):
        """Argument is a valid URI or list of URIs."""
        if isinstance(values, list):
            uris = list(self.valid_uri(parser, u) for u in values)
            setattr(namespace, self.dest, getattr(namespace, self.dest) + uris)
        else:
            uri = self.valid_uri(parser, values)
            setattr(namespace, self.dest, uri)

    @staticmethod
    def valid_uri(parser, values):
        uri = None
        if _uri_validator(values):
            uri = URIRef(values)
        else:
            parser.error(f'Invalid URI {values}')
        return uri


class OntologyUriValidator(argparse.Action):
    """Validates ontology IRI and version arguments."""

    # No public method needed
    # pylint: disable=R0903
    def __call__(self, parser, namespace, values, option_string=None):
        """First argument is a valid URI, 2nd a valid semantic version."""
        iri = None
        if _uri_validator(values[0]):
            iri = URIRef(values[0])
        else:
            parser.error(f'Invalid merge ontology URI {values[0]}')
        if not re.match(r'\d+(\.\d+){0,2}', values[1]):
            parser.error(f'Invalid merge ontology version {values[1]}')
        setattr(namespace, self.dest, [iri, values[1]])


def configure_arg_parser():
    """Configure command line parser."""
    parser = argparse.ArgumentParser(description='Ontology toolkit.')
    subparsers = parser.add_subparsers(help='sub-command help', dest='command')

    update_parser = subparsers.add_parser('update',
                                          help='Update versions and dependencies')

    output_format_group = update_parser.add_mutually_exclusive_group()
    output_format_group.add_argument(
        '-f', '--format', action='store',
        default='turtle', choices=['xml', 'turtle', 'nt'],
        help='Output format')
    output_format_group.add_argument(
        '-i', '--in-place', action="store_true",
        help="Overwrite each input file with update, preserving format")

    update_parser.add_argument('--debug', action="store_true",
                               help="Emit verbose debug output")
    update_parser.add_argument('-o', '--output',
                               type=argparse.FileType('w', encoding='utf-8'),
                               default=sys.stdout,
                               help='Path to output file. Will be ignored if '
                               '--in-place is specified.')
    update_parser.add_argument('-b', '--defined-by', action="store",
                               nargs="?", const='strict',
                               choices=['all', 'strict'],
                               help='Add rdfs:isDefinedBy to every resource defined. '
                               'If the (default) "strict" argument is provided, only '
                               'owl:Class, owl:ObjectProperty, owl:DatatypeProperty, '
                               'owl:AnnotationProperty and owl:Thing entities will be '
                               'annotated. If "all" is provided, every entity that has '
                               'any properties other than rdf:type will be annotated. '
                               'Will override any existing rdfs:isDefinedBy annotations '
                               'on the affected entities unless --retain-definedBy is '
                               'specified.')
    update_parser.add_argument('--retain-definedBy', action="store_true",
                               help='Retain existing values of rdfs:isDefinedBy')
    update_parser.add_argument('--versioned-definedBy', action="store_true",
                               help='Use versionIRI for rdfs:isDefinedBy, when available')
    update_parser.add_argument('-v', '--set-version', action="store",
                               help='Set the version of the defined ontology')
    update_parser.add_argument('--version-info', action="store",
                               nargs='?', const='auto',
                               help='Adjust versionInfo, defaults to "Version X.x.x"')
    update_parser.add_argument('-d', '--dependency-version', action="append",
                               metavar=('DEPENDENCY', 'VERSION'),
                               nargs=2, default=[],
                               help='Update the import of DEPENDENCY to VERSION')
    update_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file or directory containing OWL files")

    export_parser = subparsers.add_parser('export', help='Export ontology')

    format_parser = export_parser.add_mutually_exclusive_group()
    format_parser.add_argument('-f', '--format', action='store',
                               default='turtle',
                               choices=['xml', 'turtle', 'nt'],
                               help='Output format')
    format_parser.add_argument('-c', '--context', action=UriValidator,
                               help='Export as N-Quads in CONTEXT.')

    export_parser.add_argument('--debug', action="store_true",
                               help="Emit verbose debug output")
    export_parser.add_argument('-o', '--output',
                               type=argparse.FileType('w', encoding='utf-8'),
                               default=sys.stdout,
                               help='Path to output file.')
    export_parser.add_argument('-s', '--strip-versions', action="store_true",
                               help='Remove versions from imports.')
    export_parser.add_argument('-m', '--merge', action=OntologyUriValidator, nargs=2,
                               metavar=('IRI', 'VERSION'),
                               help='Merge all inputs into a single ontology'
                               ' with the given IRI and version')
    export_parser.add_argument('-b', '--defined-by', action="store",
                               nargs="?", const='strict',
                               choices=['all', 'strict'],
                               help='Add rdfs:isDefinedBy to every resource defined. '
                               'If the (default) "strict" argument is provided, only '
                               'owl:Class, owl:ObjectProperty, owl:DatatypeProperty, '
                               'owl:AnnotationProperty and owl:Thing entities will be '
                               'annotated. If "all" is provided, every entity that has '
                               'any properties other than rdf:type will be annotated.')
    export_parser.add_argument('--retain-definedBy', action="store_true",
                               help='When merging ontologies, retain existing values '
                               'of rdfs:isDefinedBy')
    export_parser.add_argument('--versioned-definedBy', action="store_true",
                               help='Use versionIRI for rdfs:isDefinedBy, when available')
    export_parser.add_argument('ontology', nargs="*", default=[],
                               help="Ontology file or directory containing OWL files")

    bundle_parser = subparsers.add_parser('bundle', help='Bundle ontology for release')
    bundle_parser.add_argument('--debug', action="store_true",
                               help="Emit verbose debug output")
    bundle_parser.add_argument('-v', '--variable', action="append",
                               dest='variables',
                               metavar=('VARIABLE', 'VALUE'),
                               nargs=2, default=[],
                               help='Set value of VARIABLE to VALUE')
    bundle_parser.add_argument('bundle', default='bundle.json',
                               help="JSON or YAML bundle definition")

    graphic_parser = subparsers.add_parser('graphic',
                                           help='Create PNG graphic and dot'
                                           ' file from OWL files or SPARQL Endpoint')
    graphic_parser.add_argument("-e", "--endpoint", action="store",
                                help="URI of SPARQL endpoint to use to gather data")
    which_graphic = graphic_parser.add_mutually_exclusive_group()
    which_graphic.add_argument("--schema", dest="action", action="store_const",
                               const="ontology", default="ontology",
                               help="Generate ontology import graph (default)")
    which_graphic.add_argument("--data", dest="action", action="store_const",
                               const="instances",
                               help="Analyze instances for types and links")
    graphic_parser.add_argument("--single-ontology-graphs", action="store_true",
                                help="If specified in combination with --endpoint"
                                     " when generating a schema graph, assume that every"
                                     " ontology is in its own named graph in the triple store."
                                     " Otherwise rdfs:isDefinedBy will be used to locate"
                                     " entities defined by each ontology.")
    graphic_parser.add_argument('--debug', action="store_true",
                                help="Emit verbose debug output")
    graphic_parser.add_argument('-o', '--output', action="store",
                                default=os.getcwd(),
                                help="Output directory for generated graphics")
    graphic_parser.add_argument('--show-shacl', action="store_true",
                                help="Attempts to discover which classes and properties have corresponding"
                                     " SHACL shapes and colors them green on the graph. This detection relies"
                                     " on the presence of sh:targetClass targeting, and can be confused by"
                                     " complex logical shapes or Advanced SHACL features such as SPARQL queries.")
    sampling_limits = graphic_parser.add_argument_group(title='Sampling Limits')
    sampling_limits.add_argument("--instance-limit", type=int, default=500000,
                                 help="Specify a limit on how many triples to consider that use any one"
                                      " predicate to find (default 500000). This option may result in an"
                                      " incomplete version of the diagram, missing certain links.")
    sampling_limits.add_argument("--predicate-threshold", type=int, default=10,
                                 help="Ignore predicates which occur fewer than PREDICATE_THRESHOLD times"
                                      " (default 10)")
    graph_filters = graphic_parser.add_argument_group(title="Filters (only one can be used)")
    scope_control = graph_filters.add_mutually_exclusive_group()
    scope_control.add_argument("--include", nargs="*", default=[],
                               action=UriValidator,
                               help="If specified for --schema, only ontologies matching the specified"
                                    " URIs will be shown in full detail. If specified with --data, only"
                                    " triples in the named graphs mentioned will be considered (this also"
                                    " excludes any triples in the default graph).")
    scope_control.add_argument("--include-pattern", nargs="*", default=[],
                               metavar="INCLUDE_REGEX",
                               help="If specified for --schema, only ontologies matching the specified"
                                    " URI pattern will be shown in full detail. If specified with --data,"
                                    " only triples in the named graphs matching the pattern"
                                    " will be considered (this also excludes any triples in the default"
                                    " graph). For large graphs this option is significantly slower than"
                                    " using --include.")
    scope_control.add_argument("--exclude", nargs="*", default=[],
                               action=UriValidator,
                               help="If specified for --schema, ontologies matching the specified"
                                    " URIs will be omitted from the graph. If specified with --data, "
                                    " triples in the named graphs mentioned will be excluded (this also"
                                    " excludes any triples in the default graph).")
    scope_control.add_argument("--exclude-pattern", nargs="*", default=[],
                               metavar="EXCLUDE_REGEX",
                               help="If specified for --schema, ontologies matching the specified"
                                    " URI pattern will be omitted from the graph. If specified with --data,"
                                    " triples in the named graphs matching the pattern"
                                    " will be ignored (this also excludes any triples in the default"
                                    " graph). For large graphs this option is significantly slower than"
                                    " using --exclude.")
    graphic_parser.add_argument('-v', '--version', help="Version to place in graphic",
                                action="store")
    graphic_parser.add_argument('-w', '--wee', action="store_true",
                                help="a version of the graphic with only core"
                                " information about ontology and imports")
    graphic_parser.add_argument("--no-image", action="store_true",
                                help="Do not generate PNG image, only .dot output.")
    graphic_parser.add_argument("-t", "--title", action="store",
                                help="Title to use for graph. If not supplied, the repo URI will be used if"
                                " graphing an endpoint, or 'Gist' if graphing local files.")
    graphic_parser.add_argument('ontology', nargs="*", default=[],
                                help="Ontology file, directory or name pattern")
    return parser
