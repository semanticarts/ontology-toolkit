from rdflib import Graph, URIRef
from rdflib.namespace import RDFS
from onto_tool import onto_tool

import pytest
import os

def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    # os.remove('tests/bundle/issue-138-output.ttl')


def test_bundle_no_defined_by():
    onto_tool.main([
        'bundle',
        'tests/bundle/issue-138_no_mode.yaml'])
    graph = Graph()
    graph.parse('tests/bundle/issue-138-output.ttl', format="turtle")
    assert len(graph) == 7
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/myProperty'), URIRef('https://data.clientX.com/d/ontoName'))]
    )


def test_bundle_strict_defined_by():
    onto_tool.main([
        'bundle',
        'tests/bundle/issue-138_strict_mode.yaml'])
    graph = Graph()
    graph.parse('tests/bundle/issue-138-output.ttl', format="turtle")
    assert len(graph) == 7
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/myProperty'), URIRef('https://data.clientX.com/d/ontoName'))]
    )


def test_bundle_all_defined_by():
    onto_tool.main([
        'bundle',
        'tests/bundle/issue-138_all_mode.yaml'])
    graph = Graph()
    graph.parse('tests/bundle/issue-138-output.ttl', format="turtle")
    assert len(graph) == 8
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/MyIndividual'), URIRef('https://data.clientX.com/d/ontoName')),
         (URIRef('https://data.clientX.com/myProperty'), URIRef('https://data.clientX.com/d/ontoName'))]
    )


def test_bundle_versioned_defined_by():
    onto_tool.main([
        'bundle',
        'tests/bundle/issue-138_versioned_iri.yaml'])
    graph = Graph()
    graph.parse('tests/bundle/issue-138-output.ttl', format="turtle")
    assert len(graph) == 7
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/myProperty'), URIRef('https://data.clientX.com/d/ontoName1.0.0'))]
    )