from tempfile import TemporaryDirectory

from onto_tool import onto_tool


def test_missing_file_reported(caplog):
    with TemporaryDirectory() as tempdir:
        onto_tool.main([
            'bundle', '-v', 'output', tempdir, 'tests/bundle/broken_file_ref.yaml'
        ])

    logs = caplog.text
    assert 'missing_data.ttl' in logs
    assert 'missing_with' not in logs
