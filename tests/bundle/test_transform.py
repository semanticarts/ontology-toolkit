import logging
import re
from onto_tool import onto_tool
from rdflib import Graph
from rdflib.namespace import SKOS, RDF


def test_transform_sparql():
    onto_tool.main([
        'bundle', '-v', 'lang', 'en', 'tests/bundle/transform_sparql.yaml'
    ])

    updated_graph = Graph()
    updated_graph.parse('tests/bundle/transform_sparql_data_en.ttl', format='turtle')
    without_lang = [label for label in updated_graph.objects(None, SKOS.prefLabel)
                    if label.language != 'en']
    assert len(without_lang) == 0


def test_transform_java():
    onto_tool.main([
        'bundle', '-v', 'format', 'rdf-xml', 'tests/bundle/transform_java.yaml'
    ])

    updated_graph = Graph()
    updated_graph.parse('tests/bundle/transform_sparql_data.xml', format='xml')
    types = list(updated_graph.subject_objects(RDF.type))
    assert len(types) == 2


def test_transform_shell(caplog):
    with caplog.at_level(logging.DEBUG):
        onto_tool.main([
            'bundle', 'tests/bundle/transform_shell.yaml'
        ])

    output = caplog.messages
    assert any(re.search(r'(java|openjdk) version ', message) for message in output)
