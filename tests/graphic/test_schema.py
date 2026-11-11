import re

from onto_tool import onto_tool
import pydot


def test_local_instance(tmp_path):
    onto_tool.main([
        'graphic',
        '-t', 'Local Ontology',
        '--no-image',
        '-o', f'{tmp_path}/test_schema',
        'tests/graphic/domain_ontology.ttl',
        'tests/graphic/upper_ontology.ttl',
        'tests/graphic/instance_data.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_schema.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('"Domain"', '"Upper"'),
        ('"Instances"', '"Domain"')
    ]


def test_urn_imports(tmp_path):
    onto_tool.main([
        'graphic',
        '-t', 'URN Ontology',
        '--no-image',
        '-o', f'{tmp_path}/test_urn',
        'tests/graphic/urn_importing.ttl',
        'tests/graphic/urn_imported.ttl'
    ])
    (schema_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_urn.dot')
    # URN names contain ':', which must not be parsed as a node:port separator
    edges = [(e.get_source(), e.get_destination()) for e in schema_graph.get_edges()]
    assert edges == [('"urn:example:importing"', '"urn:example:imported"')]


def test_special_class_name(tmp_path):
    onto_tool.main([
        'graphic', '--schema',
        '-t', 'Special Class Name',
        '--no-image',
        '-o', f'{tmp_path}/test_special',
        'tests/graphic/special_class_name.ttl'
    ])
    (schema_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_special.dot')
    (ontology_node,) = schema_graph.get_node('"special"')
    # Fields are separated by unescaped '|', class labels are in the second field
    fields = re.split(r'(?<!\\)\|', ontology_node.get('label').strip('"')[1:-1])
    assert sorted(fields[1].split('\\l')) == [
        'A \\| \\{B\\} \\<C\\> \\"D\\"',
        'Baz',
        'Foo & Bar',
        'Multilingual'
    ]
