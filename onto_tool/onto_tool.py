"""Toolkit for ontology maintenance and release."""
import logging
import re
import shutil
import subprocess
import sys
from os.path import basename, join, splitext

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, XSD
from rdflib.util import guess_format

import onto_tool

from .bundle import bundle_ontology
from .command_line import configure_arg_parser
from .ontograph import OntoGraf
from .utils import isfile, expand_file_ref, perform_export, find_single_ontology, \
                   add_defined_by, parse_rdf, strip_versions


# f-strings are fine in log messages
# pylint: disable=W1203
# CamelCase variable names are fine
# pylint: disable=C0103


def set_version(g, ontology, ontology_iri, version):
    """Add or replace versionIRI for the specified ontology."""
    old_version = next(g.objects(ontology, OWL.versionIRI), None)
    if old_version:
        logging.debug(f'Removing versionIRI {old_version} from {ontology}')
        g.remove((ontology, OWL.versionIRI, old_version))

    version_iri = URIRef(f"{ontology_iri}{version}")
    g.add((ontology, OWL.versionIRI, version_iri))
    logging.info(f'versionIRI {version_iri} added for {ontology}')


def set_version_info(g, ontology, version_info):
    """Add versionInfo for the ontology.

    If versionInfo is not provided, extracts ontology version from versionIRI.
    """
    version_info = version_info if version_info != 'auto' else None
    pattern = re.compile('^(.*?)(\\d+\\.\\d+\\.\\d+)?$')
    version_iri = next(g.objects(ontology, OWL.versionIRI), None)
    version = pattern.match(str(version_iri)).group(2) if version_iri else None
    if not version and not version_info:
        raise LookupError(
            f'No version found for {ontology}, must specify version info')

    old_version_info = next(g.objects(ontology, OWL.versionInfo), None)
    if old_version_info:
        logging.debug(f'Removing previous versionInfo from {ontology}')
        g.remove((ontology, OWL.versionInfo, old_version_info))

    if not version_info:
        version_info = "Version " + version
    g.add((ontology, OWL.versionInfo, Literal(version_info, datatype=XSD.string)))
    logging.info(f'versionInfo "{version_info}" added for {ontology}')


def update_dependency_versions(g, ontology, versions):
    """Update ontology dependency versions.

    The versions dict maps ontology IRI to their versions.
    Inspect the imports of the current ontology, and if they match
    (ignoring version) any of the ontology provided in the argument,
    update them to the new version.
    """
    # Gather current dependencies
    current_deps = g.objects(ontology, OWL.imports)
    for dv in versions:
        dep, ver = dv
        pattern = re.compile(f'{dep}(\\d+\\.\\d+\\.\\d+)?')
        match = next((c for c in current_deps if pattern.search(str(c))), None)
        if match:
            # Updating current dependency
            current = pattern.search(str(match)).group(1)
            if current:
                logging.debug(f'Removing dependency {current} for {dep}')
                new_version_uri = URIRef(str(match).replace(current, ver))
            else:
                logging.debug(f'Removing unversioned depenendency for {dep}')
                new_version_uri = URIRef(f'{str(match)}{ver}')
            g.remove((ontology, OWL.imports, match))

            g.add((ontology, OWL.imports, new_version_uri))
            logging.info(f'Updated dependency to {new_version_uri}')
        else:
            # New versioned dependency, assuming full URI
            new_version_uri = URIRef(f'{dep}{ver}')
            g.add((ontology, OWL.imports, new_version_uri))
            logging.info(f'Added dependency for {new_version_uri}')


def serialize_to_output_dir(tools, output, version, file):
    """Serialize ontology file using standard options."""
    base, ext = splitext(basename(file))
    output_file = join(output, f"{base}{version}{ext}")
    logging.debug(f"Serializing {file} to {output}")
    serialize_args = [
        "java",
        "-jar", join(tools, "rdf-toolkit.jar"),
        "-tfmt", "rdf-xml",
        "-sdt", "explicit",
        "-dtd",
        "-ibn",
        "-s", file,
        "-t", output_file]
    subprocess.run(serialize_args, check=True)
    return output_file


def copy_if_present(from_loc, to_loc):
    """Copy file to new location if present."""
    if isfile(from_loc):
        shutil.copy(from_loc, to_loc)


def generate_graphic(action, onto_files, endpoint, **kwargs):
    """
    Generate ontology .dot and .png graphic.

    Parameters
    ----------
    action : string
        'ontology' or 'data', depending on the type of graphic requested.
    onto_files : list(string)
        List of paths or glob patterns from which to gather ontologies.
    endpoint : string
        URL of SPARQL endpoint to use for data instead of local ontology files.


    Keyword Parameters
    ------------------
    wee : list(string)
        If None, full details for all ontologies (--wee omitted from command line).
        If empty list (-wee specified with no arguments), all ontologies are rendered compact
        Otherwise, compact display for any ontologies matching the regular expressions in the list
    outpath : string
        Path of directory where graph will be output.
    version : string
        Version to be used in graphic title.
    label_language: string
        When multiple language labels are present, use this one.
    hide: list(string)
        List of regular expressions to control which classes and/or properties
        will be hidden from the data graphic.
    include: list(string)
        List of ontology URIs to include for schema graph, or named graphs to consider
        for data graph.
    include_pattern: list(string)
        List of regex against which ontology URIs are matched for inclusion in schema graph, or
        named graphs are matched for inclusion in a data graph.
    exclude: list(string)
        List of ontology URIs to exclude from schema graph, or named graphs to exclude
        from data graph.
    exclude_pattern: list(string)
        List of regex against which ontology URIs are matched for exclusion from schema graph, or
        named graphs are matched for exclusion from a data graph.
    show_shacl: boolean
        If True, attempt to detect SHACL shapes matching classes and properties.
    concentrate_links: int
        When the number links originating from the same class that share a single predicate exceed
        this threshold, use more compact display. Setting the value to 0 disables this behavior.
    cache: TextIOWrapper
        Read cached query results
    save_cache: TextIOWrapper
        Save query results as JSON to use with --cache

    Returns
    -------
    None.

    """
    all_files = [file for ref in onto_files for file in expand_file_ref(ref)]
    og = OntoGraf(all_files, repo=endpoint, **kwargs)
    if kwargs['cache'] and (endpoint or all_files):
        logging.warning('Reading cached data from %s, ignoring endpoint/files',
                        kwargs['cache'].name)
    if endpoint and all_files:
        logging.warning('Endpoint specified, ignoring files')
    if action == 'ontology':
        if endpoint:
            og.gather_schema_info_from_repo()
        else:
            og.gather_schema_info_from_files()
        og.create_schema_graf()
    else:
        og.gather_instance_info()
        og.create_instance_graf()


def __suppress_ssl_certificate_check():
    # only if needed
    # pylint: disable=C0415
    # Need to poke into ssl to override
    # pylint: disable=W0212
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context


def export_ontology(args, output_format):
    """Export one or more files as a single output.

    Optionally, strips dependency versions and merges ontologies into
    a single new ontology.
    """
    context = args.context if 'context' in args and args.context else None
    defined_by = args.defined_by if 'defined_by' in args and args.defined_by else None

    perform_export(args.output, output_format, args.ontology,
                   context,
                   'strip_versions' in args and args.strip_versions,
                   args.merge if 'merge' in args and args.merge else None,
                   defined_by,
                   args.retain_definedBy,
                   args.versioned_definedBy)


def update_ontology(args, output_format):
    """Maintenance updates for ontology files."""
    for onto_file in [file for ref in args.ontology for file in expand_file_ref(ref)]:
        g = Graph()
        orig_format = guess_format(onto_file)
        parse_rdf(g, onto_file, orig_format)
        logging.debug(f'{onto_file} has {len(g)} triples')

        # locate ontology
        ontology = find_single_ontology(g, onto_file)
        if not ontology:
            logging.warning(f'Ignoring {onto_file}, no ontology found')
            continue

        ontology_iri = ontology

        # Set version
        if 'set_version' in args and args.set_version:
            set_version(g, ontology, ontology_iri, args.set_version)
        if 'version_info' in args and args.version_info:
            try:
                set_version_info(g, ontology, args.version_info)
            except LookupError as e:
                logging.error(e)
                continue

        # Add rdfs:isDefinedBy
        if 'defined_by' in args and args.defined_by:
            add_defined_by(g, ontology_iri, mode=args.defined_by,
                           replace=not args.retain_definedBy,
                           versioned=args.versioned_definedBy)

        # Update dep versions
        if 'dependency_version' in args and args.dependency_version:
            update_dependency_versions(g, ontology, args.dependency_version)

        # Remove dep versions
        if 'strip_versions' in args and args.strip_versions:
            strip_versions(g, ontology)

        output_updated_ontology(args, g, onto_file, orig_format, output_format)


def output_updated_ontology(args, g, onto_file, orig_format, output_format):
    """Output the updated ontology in the original format."""
    if args.in_place:
        adjusted_format = 'pretty-xml' if orig_format == 'xml' else orig_format
        g.serialize(destination=onto_file,
                    format=adjusted_format,
                    encoding='utf-8')
    else:
        serialized = g.serialize(format=output_format)
        args.output.write(serialized)


def main(arguments):
    """Do the thing."""
    args = configure_arg_parser().parse_args(args=arguments)

    if 'debug' in args and args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.version:
        logging.info("onto-tool v%s", onto_tool.VERSION)
        return

    if args.insecure:
        __suppress_ssl_certificate_check()

    if args.command == 'bundle':
        bundle_ontology(args.variables, args.bundle)
        return

    if args.command == 'graphic':
        generate_graphic(args.action, args.ontology, args.endpoint,
                         limit=args.instance_limit, threshold=args.predicate_threshold,
                         single_graph=args.single_ontology_graphs,
                         wee=args.wee, outpath=args.output, version=args.version,
                         no_image=args.no_image, title=args.title, hide=args.hide,
                         label_language=args.label_language,
                         concentrate_links=args.link_concentrator_threshold,
                         include=args.include, exclude=args.exclude,
                         include_pattern=args.include_pattern,
                         exclude_pattern=args.exclude_pattern,
                         show_shacl=args.show_shacl,
                         cache=args.cache,
                         save_cache=args.save_cache)
        return

    of = 'pretty-xml' if args.format == 'xml' else args.format

    if args.command == 'export':
        export_ontology(args, of)
    else:
        update_ontology(args, of)


def run_tool():
    """Entry point for executable script."""
    main(sys.argv[1:] if len(sys.argv) > 1 else ['-h'])
