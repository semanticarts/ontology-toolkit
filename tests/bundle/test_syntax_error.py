from onto_tool import onto_tool
from pytest import raises
import re


def test_syntax_export(caplog, tmp_path):
    with raises(SystemExit) as wrapped_exit:
        onto_tool.main([
            'bundle', '-v', 'output', f'{tmp_path}', 'tests/bundle/syntax_error.yaml'
        ])
    assert wrapped_exit.type == SystemExit
    assert wrapped_exit.value.code == 1

    logs = caplog.text
    assert re.search(r'Error parsing .*malformed_rdf.ttl at 3', logs)
