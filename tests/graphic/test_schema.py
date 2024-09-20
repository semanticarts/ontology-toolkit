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
        ('Domain', 'Upper'),
        ('Instances', 'Domain')
    ]


def test_remote_instance(tmp_path, sparql_endpoint):
    repo_uri = 'https://my.rdfdb.com/repo/sparql'
    rdf_files = ['tests/graphic/domain_ontology.ttl',
                 'tests/graphic/upper_ontology.ttl',
                 'tests/graphic/instance_data.ttl']
    sparql_endpoint(repo_uri, rdf_files)

    onto_tool.main([
        'graphic',
        '--endpoint', f'{repo_uri}',
        '-t', 'Remote Ontology',
        '--no-image',
        '-o', f'{tmp_path}/test_schema'
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_schema.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('Domain', 'Upper'),
        ('Instances', 'Domain')
    ]


def test_remote_graphs(tmp_path, sparql_endpoint):
    repo_uri = 'https://my.rdfdb.com/repo/sparql'
    rdf_files = ['tests/graphic/domain_ontology.trig',
                 'tests/graphic/upper_ontology.trig',
                 'tests/graphic/instance_data.trig']
    sparql_endpoint(repo_uri, rdf_files)

    onto_tool.main([
        'graphic', '--single-ontology-graphs',
        '--endpoint', f'{repo_uri}',
        '-t', 'Remote Ontology',
        '--no-image',
        '-o', f'{tmp_path}/test_schema'
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_schema.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [
        ('Domain', 'Upper'),
        ('Instances', 'Domain')
    ]
