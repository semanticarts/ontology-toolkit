from onto_tool import onto_tool
from glob import glob
from os.path import basename


def test_markdown_table():
    onto_tool.main([
        'bundle', '-v', 'output', 'tests-output/bundle',
        'tests/bundle/markdown.yaml'
    ])

    html_text = open('tests-output/bundle/Table.html').read()
    assert '<table' in html_text.lower()


def test_markdown_bulk():
    onto_tool.main([
        'bundle', '-v', 'output', 'tests-output/bundle',
        'tests/bundle/bulk_md.yaml'
    ])

    inc_no_exc = [basename(f) for f in glob('tests-output/bundle/bulk_md/inc_no_exc/*')]
    assert sorted(inc_no_exc) == ['a1.html']

    exc_no_inc = [basename(f) for f in glob('tests-output/bundle/bulk_md/exc_no_inc/*')]
    assert sorted(exc_no_inc) == ['a1.html', 'c3.html']

    inc_and_exc = [basename(f) for f in glob('tests-output/bundle/bulk_md/inc_and_exc/*')]
    assert sorted(inc_and_exc) == ['b2.html', 'c3.html']

