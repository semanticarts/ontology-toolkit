from onto_tool import onto_tool
import csv
from os.path import isfile
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
    assert re.search(r'Verification ASK .*verify_label.* False', caplog.text)
    assert re.search(r'Verification ASK .*verify_domain.* False', caplog.text)


def test_verify_select_multiple(caplog):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', 'tests/bundle/verify_select_multiple.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1

    logs = caplog.text
    assert re.search(r'Verification query .*verify_label_select', logs)
    assert 'http://example.com/unlabeled' in logs
    assert re.search(r'Verification query .*verify_domain_select', logs)
    assert 'http://example.com/nonexistent' in logs

    with open('tests/bundle/verify_select_results/verify_label_select_query.csv') as errors:
        actual = list(row for row in csv.DictReader(errors))
    expected = [{'unlabeled': 'http://example.com/unlabeled'}]
    assert actual == expected

    with open('tests/bundle/verify_select_results/verify_domain_select_query.csv') as errors:
        actual = list(row for row in csv.DictReader(errors))
    expected = [{'domain': 'http://example.com/nonexistent'}]
    assert actual == expected


def test_verify_construct(caplog):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', 'tests/bundle/verify_construct.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1

    logs = caplog.text
    assert re.search(r'Verification query .*verify_label_construct', logs)
    assert 'http://example.com/unlabeled' in logs
    assert re.search(r'Verification query .*verify_domain_construct', logs)
    assert 'http://example.com/nonexistent' in logs

    validation_graph = Graph()
    validation_graph.parse(
        'tests/bundle/verify_construct_results/verify_label_construct_query.ttl',
        format='turtle')
    sh = Namespace('http://www.w3.org/ns/shacl#')
    errors = [validation_graph.subjects(RDF.type, sh.ValidationResult)]
    assert len(errors) == 1

    validation_graph = Graph()
    validation_graph.parse(
        'tests/bundle/verify_construct_results/verify_domain_construct_query.ttl',
        format='turtle')
    sh = Namespace('http://www.w3.org/ns/shacl#')
    errors = [validation_graph.subjects(RDF.type, sh.ValidationResult)]
    assert len(errors) == 1

    # Should handle a query that generates no errors
    assert not isfile('test/bundle/verify_construct_results/verify_no_errors_construct_query.ttl')


def test_verify_construct_endpoint(caplog):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', 'tests/bundle/verify_construct_endpoint.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1

    logs = caplog.text
    assert re.search(r'Verification query .*verify_fixed_error', logs)
    assert 'fails' in logs

    validation_graph = Graph()
    validation_graph.parse(
        'tests/bundle/verify_construct_results/verify_fixed_error.ttl',
        format='turtle')
    sh = Namespace('http://www.w3.org/ns/shacl#')
    errors = [validation_graph.subjects(RDF.type, sh.ValidationResult)]
    assert len(errors) == 1


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
