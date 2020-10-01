from onto_tool import onto_tool
import csv


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_sparql_queries():
    onto_tool.main([
        'bundle', 'tests/bundle/sparql.yaml'
    ])
    with open('tests/bundle/sparql.csv') as csvfile:
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
