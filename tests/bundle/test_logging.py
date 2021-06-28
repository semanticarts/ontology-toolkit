import logging

from onto_tool import onto_tool


def test_action_message(caplog):
    with caplog.at_level(logging.INFO):
        onto_tool.main([
            'bundle', 'tests/bundle/logging.yaml'
        ])

    logs = caplog.text
    assert 'Running from tests' in logs
    assert 'DEBUG' not in logs


def test_debug_log(caplog):
    with caplog.at_level(logging.DEBUG):
        onto_tool.main([
            'bundle', '--debug', 'tests/bundle/logging.yaml'
        ])

    logs = caplog.text
    assert 'Running from tests' in logs
    assert 'DEBUG' in logs
