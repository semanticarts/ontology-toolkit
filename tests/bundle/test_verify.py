from onto_tool import onto_tool
import csv
from pytest import raises
import re
from rdflib import Graph
from rdflib.namespace import Namespace, RDF


def test_verify_select(caplog):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', 'tests/bundle/verify_select.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1

    logs = caplog.text
    assert 'Verification query inline' in logs
    assert 'http://example.com/unlabeled' in logs

    with open('tests/bundle/verify_select_errors.csv') as errors:
        actual = list(row for row in csv.DictReader(errors))
    expected = [{'unlabeled': 'http://example.com/unlabeled'}]
    assert actual == expected


def test_verify_ask(caplog):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', 'tests/bundle/verify_ask.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1
    assert re.search(r'Verification ASK .* False', caplog.text)


def test_verify_shacl(caplog):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', 'tests/bundle/verify_shacl.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1

    logs = caplog.text
    assert 'SHACL verification' in logs
    assert 'skos:prefLabel' in logs

    validation_graph = Graph()
    validation_graph.parse('tests/bundle/verify_shacl_errors.ttl', format='turtle')
    sh = Namespace('http://www.w3.org/ns/shacl#')
    errors = [validation_graph.subjects(RDF.type, sh.ValidationResult)]
    assert len(errors) == 1
