from rdflib import Graph, URIRef
from rdflib.namespace import RDFS
from onto_tool import onto_tool


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_update_no_defined_by(capsys):
    onto_tool.main([
        'update',
        'tests/issue-36-defined-by.ttl'])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert len(graph) == 5
    assert len(list(graph.subject_objects(RDFS.isDefinedBy))) == 0


def test_update_strict_defined_by(capsys):
    capsys.readouterr()
    onto_tool.main([
        'update',
        '-b', 'strict',
        'tests/issue-36-defined-by.ttl'])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert len(graph) == 6
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/myProperty'), URIRef('https://data.clientX.com/d/ontoName'))]
    )


def test_update_all_defined_by(capsys):
    onto_tool.main([
        'update',
        '-b', 'all',
        'tests/issue-36-defined-by.ttl'])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert len(graph) == 7
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/MyIndividual'), URIRef('https://data.clientX.com/d/ontoName')),
         (URIRef('https://data.clientX.com/myProperty'), URIRef('https://data.clientX.com/d/ontoName'))]
    )
