from rdflib import Graph, URIRef, Literal
from rdflib.namespace import OWL, XSD, RDF, RDFS
from onto_tool import onto_tool


def lists_equal(list_one, list_two):
    return len(list_one) == len(list_two) and sorted(list_one) == sorted(list_two)


def test_export_strip_versions(capsys):
    onto_tool.main([
        'export', '-s',
        'tests/update-tests.ttl'
    ])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert lists_equal(
        list(graph.subject_objects(OWL.imports)),
        [(URIRef('https://data.clientX.com/d/ontoName'),
          URIRef('https://data.clientX.com/d/coreOntology'))]
    )


def test_export_merge(capsys):
    onto_tool.main([
        'export',
        '-m', 'https://data.clientX.com/d/coreOntology', '2.0.0',
        '-b', 'strict',
        'tests/merge-subdomain.ttl', 'tests/merge-top.ttl'
    ])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert lists_equal(
        list(graph.subjects(RDF.type, OWL.Ontology)),
        [URIRef('https://data.clientX.com/d/coreOntology')]
    )
    assert lists_equal(
        list(graph.subject_objects(OWL.imports)),
        [(URIRef('https://data.clientX.com/d/coreOntology'),
          URIRef('https://come.external.com/ontology1.3.0'))]
    )
    assert lists_equal(
        list(graph.subject_objects(OWL.versionIRI)),
        [(URIRef('https://data.clientX.com/d/coreOntology'),
          URIRef('https://data.clientX.com/d/coreOntology2.0.0'))]
    )
    assert lists_equal(
        list(graph.subject_objects(OWL.versionInfo)),
        [(URIRef('https://data.clientX.com/d/coreOntology'),
          Literal('Created by merge tool.', datatype=XSD.string))]
    )
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/myProperty'),
          URIRef('https://data.clientX.com/d/coreOntology'))]
    )


def test_versioned_defined_by(capsys):
    onto_tool.main([
        'export',
        '-m', 'https://data.clientX.com/d/coreOntology', '2.0.0',
        '-b', 'strict',
        '--versioned-definedBy',
        'tests/merge-subdomain.ttl', 'tests/merge-top.ttl'
    ])
    updated = capsys.readouterr().out
    graph = Graph()
    graph.parse(data=updated, format="turtle")
    assert lists_equal(
        list(graph.subject_objects(RDFS.isDefinedBy)),
        [(URIRef('https://data.clientX.com/myProperty'),
          URIRef('https://data.clientX.com/d/coreOntology2.0.0'))]
    )
