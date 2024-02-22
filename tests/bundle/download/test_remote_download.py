import csv
import logging
from tempfile import TemporaryDirectory

from onto_tool import onto_tool


def test_download():
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/download/remote_rename.yaml'
        ])
        with open(f'{tempdir}/sparql.csv') as csvfile:
            actual = list(row for row in csv.DictReader(csvfile))
        expected = [
            {'def_by': 'https://w3id.org/semanticarts/ontology/versioning'}
        ]
        assert actual == expected


def test_remote_query():
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/download/remote_direct.yaml'
        ])
        with open(f'{tempdir}/sparql.csv') as csvfile:
            actual = list(row for row in csv.DictReader(csvfile))
        expected = [
            {'def_by': 'https://w3id.org/semanticarts/ontology/gistCore'}
        ]
        assert actual == expected


def test_missing_download_reported(caplog):
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/download/missing_reference.yaml'
        ])

    logs = caplog.text
    assert 'non-existent.ttl' in logs


def test_missing_include_reported(caplog):
    caplog.set_level(logging.INFO)
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/download/missing_include.yaml'
        ])

    logs = caplog.text
    assert 'must have an include' in logs


def test_wildcard_reported(caplog):
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/download/invalid_wildcard.yaml'
        ])

    logs = caplog.text
    assert 'wildcard' in logs
