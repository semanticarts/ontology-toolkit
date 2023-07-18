from onto_tool import onto_tool


def test_markdown_table():
    onto_tool.main([
        'bundle', '-v', 'output', 'tests-output/bundle',
        'tests/bundle/markdown.yaml'
    ])

    html_text = open('tests-output/bundle/Table.html').read()
    assert '<table' in html_text.lower()