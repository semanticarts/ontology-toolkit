from onto_tool import onto_tool
import pydot


def test_local_instance(tmp_path):
    out_file = tmp_path / 'test_schema'
    onto_tool.main([
        'graphic',
        '-t', 'Local Ontology',
        '--no-image',
        '-o', f'{out_file}',
        'tests/graphic/domain_ontology.ttl',
        'tests/graphic/upper_ontology.ttl',
        'tests/graphic/instance_data.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{out_file}.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('Domain', 'Upper'),
        ('Instances', 'Domain')
    ]
