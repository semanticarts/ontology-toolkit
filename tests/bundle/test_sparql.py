from onto_tool import onto_tool
import csv
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDFS, SKOS


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_sparql_queries(tmp_path):
    onto_tool.main([
        'bundle', '-v', 'output', f'{tmp_path}', 'tests/bundle/sparql.yaml'
    ])
    with open(f'{tmp_path}/sparql.csv') as csvfile:
        actual = list(row for row in csv.DictReader(csvfile))
    expected = [
        {'s': 'https://data.clientX.com/d/topOntology',
         'p': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
         'o': 'http://www.w3.org/2002/07/owl#Ontology'},
        {'s': 'https://data.clientX.com/d/topOntology',
         'p': 'http://www.w3.org/2000/01/rdf-schema#definedBy',
         'o': 'urn:test-sparql-queries'}
    ]
    assert actual == expected


def test_sparql_updates(tmp_path):
    onto_tool.main([
        '-k', 'bundle', '-v', 'output', f'{tmp_path}', 'tests/bundle/sparql_update.yaml'
    ])

    with open(f'{tmp_path}/sparql_update_select.csv') as csvfile:
        actual = list(row for row in csv.DictReader(csvfile))
    expected = [
        {'person': 'http://example.com/John',
         'name': 'John'},
        {'person': 'http://example.com/Jane',
         'name': 'Jane'},
    ]
    assert actual == expected

    constructed_graph = Graph()
    constructed_graph.parse(f'{tmp_path}/sparql_update_construct.xml', format='xml')
    labels = list(constructed_graph.subject_objects(SKOS.prefLabel))
    assert lists_equal([(URIRef('http://example.com/John'), Literal('John Johnson')),
                        (URIRef('http://example.com/Jane'), Literal('Jane Johnson'))],
                       labels)


def test_each_file(tmp_path):
    onto_tool.main([
        'bundle', '-v', 'output', f'{tmp_path}', 'tests/bundle/sparql-each.yaml'
    ])

    # Verify CONSTRUCT
    constructed_graph = Graph()
    constructed_graph.parse(f'{tmp_path}/each/construct/upper_ontology.ttl', format='turtle')
    labels = list(constructed_graph.subject_objects(SKOS.prefLabel))
    assert len(labels) == 5
    constructed_graph = Graph()
    constructed_graph.parse(f'{tmp_path}/each/construct/domain_ontology.ttl', format='turtle')
    labels = list(constructed_graph.subject_objects(SKOS.prefLabel))
    assert len(labels) == 6

    # Verify SELECT
    with open(f'{tmp_path}/each/select/upper_ontology.csv') as csvfile:
        actual = list(row['label'] for row in csv.DictReader(csvfile))
    expected = ["Person", "Upper Ontology", "has phone number", "is friend of", "is private"]
    assert actual == expected
    with open(f'{tmp_path}/each/select/domain_ontology.csv') as csvfile:
        actual = list(row['label'] for row in csv.DictReader(csvfile))
    expected = ["Domain Ontology", "School", "Student", "Teacher", "teaches", "works for"]
    assert actual == expected

    # Verify UPDATE
    assert actual == expected
    constructed_graph = Graph()
    constructed_graph.parse(f'{tmp_path}/each/update/upper_ontology.ttl', format='turtle')
    labels = list(constructed_graph.subject_objects(SKOS.prefLabel))
    assert len(labels) == 5
    assert not list(constructed_graph.subject_objects(RDFS.label))
    constructed_graph = Graph()
    constructed_graph.parse(f'{tmp_path}/each/update/domain_ontology.ttl', format='turtle')
    labels = list(constructed_graph.subject_objects(SKOS.prefLabel))
    assert len(labels) == 6
    assert not list(constructed_graph.subject_objects(RDFS.label))
