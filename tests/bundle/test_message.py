import logging
from re import search

from onto_tool import onto_tool


def test_action_message(caplog, tmp_path):
    caplog.set_level(logging.INFO)
    onto_tool.main([
        'bundle', '-v', 'output', f'{tmp_path}', 'tests/bundle/message.yaml'
    ])

    logs = caplog.text
    print(logs)
    assert search(r'INFO.*Test SPARQL Query from tests', logs)
