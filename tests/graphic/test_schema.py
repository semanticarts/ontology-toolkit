from onto_tool import onto_tool
import pydot


def test_local_instance():
    onto_tool.main([
        'graphic',
        '-t', 'Local Ontology',
        '--no-image',
        '-o', 'tests-output/graphic/test_schema',
        'tests/graphic/domain_ontology.ttl',
        'tests/graphic/upper_ontology.ttl',
        'tests/graphic/instance_data.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/test_schema.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('Domain', 'Upper'),
        ('Instances', 'Domain')
    ]
