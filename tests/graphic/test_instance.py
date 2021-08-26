from onto_tool import onto_tool
import glob
import pydot


def test_local_instance():
    onto_tool.main([
                       'graphic', '--predicate-threshold', '0', '--data',
                       '-t', 'Local Instance Data',
                       '--no-image',
                       '-o', 'tests/graphic/test_instance'
                   ] + glob.glob('tests/graphic/*.ttl'))
    (instance_graph,) = pydot.graph_from_dot_file('tests/graphic/test_instance.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('"http://example.com/Student"', '"http://example.com/Person"'),
        ('"http://example.com/Teacher"', '"http://example.com/School"'),
        ('"http://example.com/Teacher"', '"http://example.com/Student"')
    ]
