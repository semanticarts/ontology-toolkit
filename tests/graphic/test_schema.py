from onto_tool import onto_tool
import glob
import pydot


def test_local_instance():
    onto_tool.main([
                       'graphic',
                       '-t', 'Local Ontology',
                       '--no-image',
                       '-o', 'tests/graphic/test_schema'
                   ] + glob.glob('tests/graphic/*.ttl'))
    (instance_graph,) = pydot.graph_from_dot_file('tests/graphic/test_schema.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('Domain', 'Upper'),
        ('Instances', 'Domain')
    ]
