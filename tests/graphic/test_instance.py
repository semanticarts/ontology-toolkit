from onto_tool import onto_tool
import glob
import pydot


def test_local_instance():
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '-t', 'Local Instance Data',
        '--no-image',
        '-o', 'tests-output/graphic/test_instance',
        'tests/graphic/domain_ontology.ttl',
        'tests/graphic/upper_ontology.ttl',
        'tests/graphic/instance_data.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/test_instance.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('"http://example.com/Student"', '"http://example.com/Person"'),
        ('"http://example.com/Teacher"', '"http://example.com/School"'),
        ('"http://example.com/Teacher"', '"http://example.com/Student"')
    ]


def test_multi_language():
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '-t', 'Multi Language Labels',
        '--no-image',
        '-o', 'tests-output/graphic/test_multi_lingual_en',
        'tests/graphic/multi_language.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/test_multi_lingual_en.dot')
    edges = list(sorted((e.get_source(), e.get_label(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('"http://example.com/Person"', 'likes', '"http://example.com/Dessert"')
    ]

    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '-t', 'Multi Language Labels',
        '--no-image', '--label-language', 'fr',
        '-o', 'tests-output/graphic/test_multi_lingual_fr',
        'tests/graphic/multi_language.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/test_multi_lingual_fr.dot')
    edges = list(sorted((e.get_source(), e.get_label(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('"http://example.com/Person"', 'aime', '"http://example.com/Dessert"')
    ]


def test_inheritance():
    onto_tool.main([
                       'graphic', '--predicate-threshold', '0', '--data',
                       '-t', 'Inheritance is Difficult',
                       '--no-image',
                       '-o', 'tests-output/graphic/test_inheritance',
                       'tests/graphic/inheritance_hierarchy.ttl'
                   ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/test_inheritance.dot')
    edges = list(sorted((e.get_source(), e.get_label() or '', e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('"http://example.org/Person"', 'memberOf', '"http://example.org/Organization"'),
        ('"http://example.org/Professor"', '', '"http://example.org/Person"'),
        ('"http://example.org/Professor"', 'memberOf', '"http://example.org/SocialClub"'),
        ('"http://example.org/Professor"', 'residesAt', '"http://example.org/SingleFamilyHome"'),
        ('"http://example.org/Student"', '', '"http://example.org/Person"'),
        ('"http://example.org/Student"', 'memberOf', '"http://example.org/Fraternity"'),
        ('"http://example.org/Student"', 'residesAt', '"http://example.org/Apartment"')
    ]
    assert 'age' in instance_graph.get_node('"http://example.org/Person"')[0].get_label()
    assert 'age' not in instance_graph.get_node('"http://example.org/Student"')[0].get_label()


def test_verify_construct(caplog):
    onto_tool.main([
                       'graphic', '--data',
                       '-t', 'Local Instance Data',
                       '--no-image',
                       '-o', 'tests-output/graphic/test_instance'
                   ] + glob.glob('tests/graphic/*_ontology.ttl'))
    logs = caplog.text
    assert 'No data found' in logs


def test_concentration():
    # First, with concentration
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '--debug',
        '-t', 'Looney Tunes',
        '--no-image',
        '-o', 'tests-output/graphic/concentration',
        'tests/graphic/concentration.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/concentration.dot')
    assert 1 == sum(1 for e in instance_graph.get_edges() if e.get_label() == 'playsWith')

    # Then, without
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '-t', 'Looney Tunes',
        '--no-image',
        '--link-concentrator-threshold', '0',
        '-o', 'tests-output/graphic/concentration',
        'tests/graphic/concentration.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file('tests-output/graphic/concentration.dot')
    assert 4 == sum(1 for e in instance_graph.get_edges() if e.get_label() == 'playsWith')
