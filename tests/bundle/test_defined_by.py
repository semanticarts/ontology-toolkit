from onto_tool import onto_tool
import csv
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDFS, SKOS


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_defined_by():
    onto_tool.main([
        'bundle', '-v', 'output', 'tests-output/bundle', 'tests/bundle/defined_by.yaml'
    ])

    # Verify default
    output_graph = Graph()
    output_graph.parse(
        'tests-output/bundle/defined_by_default.ttl', format='turtle')
    defined = list(output_graph.subject_objects(RDFS.isDefinedBy))
    assert lists_equal(defined,
                       [(URIRef('https://data.clientX.com/myProperty'),
                         URIRef('https://data.clientX.com/d/ontoName'))])
    # Verify strict
    output_graph = Graph()
    output_graph.parse(
        'tests-output/bundle/defined_by_strict.ttl', format='turtle')
    defined = list(output_graph.subject_objects(RDFS.isDefinedBy))
    assert lists_equal(defined,
                       [(URIRef('https://data.clientX.com/myProperty'),
                         URIRef('https://data.clientX.com/d/ontoName'))])
    # Verify full
    output_graph = Graph()
    output_graph.parse(
        'tests-output/bundle/defined_by_full.ttl', format='turtle')
    defined = list(output_graph.subject_objects(RDFS.isDefinedBy))
    assert lists_equal(defined,
                       [(URIRef('https://data.clientX.com/myProperty'),
                         URIRef('https://data.clientX.com/d/ontoName')),
                        (URIRef('https://data.clientX.com/MyIndividual'),
                         URIRef('https://data.clientX.com/d/ontoName'))])
    # Verify all
    output_graph = Graph()
    output_graph.parse(
        'tests-output/bundle/defined_by_all.ttl', format='turtle')
    defined = list(output_graph.subject_objects(RDFS.isDefinedBy))
    assert lists_equal(defined,
                       [(URIRef('https://data.clientX.com/myProperty'),
                         URIRef('https://data.clientX.com/d/ontoName')),
                        (URIRef('https://data.clientX.com/MyIndividual'),
                         URIRef('https://data.clientX.com/d/ontoName')),
                        (URIRef('https://data.clientX.com/randomStub'),
                         URIRef('https://data.clientX.com/d/ontoName'))])
