from tempfile import TemporaryDirectory
from onto_tool import onto_tool
import csv
from rdflib import Graph


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_reasoning_queries():
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/reasoning/reasoning.yaml'
        ])

        constructed_graph = Graph()
        constructed_graph.parse(f'{tempdir}/none.ttl', format='ttl')
        assert len(constructed_graph) == 3

        with open(f'{tempdir}/rdfs.csv') as csvfile:
            actual = list(row for row in csv.DictReader(csvfile))
        expected = [
            {'s': 'https://data.clientX.com/Complex',
             'type': 'https://data.clientX.com/IntermediateClass'},
            {'s': 'https://data.clientX.com/Complex',
             'type': 'https://data.clientX.com/SimpleBaseClass'},
            {'s': 'https://data.clientX.com/Intermediate',
             'type': 'https://data.clientX.com/IntermediateClass'},
            {'s': 'https://data.clientX.com/Intermediate',
             'type': 'https://data.clientX.com/SimpleBaseClass'},
            {'s': 'https://data.clientX.com/Simple',
             'type': 'https://data.clientX.com/SimpleBaseClass'}
        ]
        assert actual == expected

        with open(f'{tempdir}/owlrl.csv') as csvfile:
            actual = list(row for row in csv.DictReader(csvfile))
        expected = [
            {'s': 'https://data.clientX.com/Complex',
             'type': 'https://data.clientX.com/ComplexClass'},
            {'s': 'https://data.clientX.com/Complex',
             'type': 'https://data.clientX.com/IntermediateClass'},
            {'s': 'https://data.clientX.com/Complex',
             'type': 'https://data.clientX.com/SimpleBaseClass'},
            {'s': 'https://data.clientX.com/Intermediate',
             'type': 'https://data.clientX.com/IntermediateClass'},
            {'s': 'https://data.clientX.com/Intermediate',
             'type': 'https://data.clientX.com/SimpleBaseClass'},
            {'s': 'https://data.clientX.com/Simple',
             'type': 'https://data.clientX.com/SimpleBaseClass'}
        ]
        assert actual == expected
