from onto_tool import onto_tool
from rdflib import Graph
from rdflib.namespace import SKOS


def test_transform_sparql():
    onto_tool.main([
        'bundle', '-v', 'lang', 'en', 'tests/bundle/transform_sparql.yaml'
    ])

    updated_graph = Graph()
    updated_graph.parse('tests/bundle/transform_sparql_data_en.ttl', format='turtle')
    without_lang = [label for label in updated_graph.objects(None, SKOS.prefLabel)
                    if label.language != 'en']
    assert len(without_lang) == 0
