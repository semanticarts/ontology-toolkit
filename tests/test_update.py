from rdflib import Graph, URIRef, Literal
from rdflib.namespace import OWL, XSD
from onto_tool import onto_tool


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_update_version(capsys):
    onto_tool.main([
        'update',
        '-v', '2.0.0',
        '--version-info', "Release 2.0.0",
        'tests/update-tests.ttl'
    ])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert lists_equal(
        list(graph.subject_objects(OWL.versionIRI)),
        [(URIRef('https://data.clientX.com/d/ontoName'),
          URIRef('https://data.clientX.com/d/ontoName2.0.0'))]
    )
    assert lists_equal(
        list(graph.subject_objects(OWL.versionInfo)),
        [(URIRef('https://data.clientX.com/d/ontoName'),
          Literal('Release 2.0.0', datatype=XSD.string))]
    )


def test_update_dependency(capsys):
    onto_tool.main([
        'update',
        '-d', 'https://data.clientX.com/d/coreOntology', '2.0.0',
        'tests/update-tests.ttl'
    ])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert lists_equal(
        list(graph.subject_objects(OWL.imports)),
        [(URIRef('https://data.clientX.com/d/ontoName'),
          URIRef('https://data.clientX.com/d/coreOntology2.0.0'))]
    )
