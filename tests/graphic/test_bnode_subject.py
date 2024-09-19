import os
from onto_tool import onto_tool
import pydot
import re


def test_filter_bnode_subjects(tmp_path):
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '-t', 'Blank Node Subjects Filtered',
        '--no-image',
        '-o', f'{tmp_path}/test_filter_bnode_subjects',
        'tests/graphic/issue-116-bnode-subjects.ttl'
    ])
    assert not os.path.isfile(f'{tmp_path}/test_filter_bnode_subjects.dot')


def test_show_bnode_subjects(tmp_path):
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '--show-bnode-subjects',
        '-t', 'Blank Node Subjects Shown',
        '--no-image',
        '-o', f'{tmp_path}/test_show_bnode_subjects',
        'tests/graphic/issue-116-bnode-subjects.ttl',
        'tests/graphic/issue-116-ontology.ttl'
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_show_bnode_subjects.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [('"http://example.org/Person"', '"http://example.org/State"')]


def test_show_named_subjects(tmp_path):
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--data',
        '--show-bnode-subjects',
        '-t', 'Named Node Subjects',
        '--no-image',
        '-o', f'{tmp_path}/test_named_subjects',
        'tests/graphic/issue-116-named-subjects.ttl',
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_named_subjects.dot')
    edges = list(sorted((e.get_source(), e.get_destination()) for e in instance_graph.get_edges()))
    assert edges == [('"http://example.org/Person"', '"http://example.org/State"')]


def test_show_ont_bnode_subjects(tmp_path):
    onto_tool.main([
        'graphic', '--predicate-threshold', '0', '--schema',
        '--show-bnode-subjects',
        '-t', 'Ontology Named Node Subjects',
        '--no-image',
        '-o', f'{tmp_path}/test_ont_bnode_subjects',
        'tests/graphic/issue-116-ontology.ttl',
    ])
    (instance_graph,) = pydot.graph_from_dot_file(f'{tmp_path}/test_ont_bnode_subjects.dot')
    label = instance_graph.get_nodes()[1].get("label")
    assert re.sub(r"n[0-9a-fA-F]{34}", "BNODE_ID", label) == '"{issue-116-ontology.ttl\l\lSmallOnt||residesIn|name||Person\lState\lClass1\lClass2\lBNODE_ID}"'
