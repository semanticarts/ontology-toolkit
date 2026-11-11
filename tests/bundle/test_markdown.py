import pytest

from onto_tool import onto_tool
from onto_tool.mdutils import md2html
from glob import glob
from os.path import basename


def test_markdown_table(tmp_path):
    onto_tool.main([
        'bundle', '-v', 'output', f'{tmp_path}',
        'tests/bundle/markdown.yaml'
    ])

    html_text = open(f'{tmp_path}/Table.html').read()
    assert '<table' in html_text.lower()


def test_markdown_bulk(tmp_path):
    onto_tool.main([
        'bundle', '-v', 'output', f'{tmp_path}',
        'tests/bundle/bulk_md.yaml'
    ])

    inc_no_exc = [basename(f) for f in glob(f'{tmp_path}/bulk_md/inc_no_exc/*')]
    assert sorted(inc_no_exc) == ['a1.html']

    exc_no_inc = [basename(f) for f in glob(f'{tmp_path}/bulk_md/exc_no_inc/*')]
    assert sorted(exc_no_inc) == ['a1.html', 'c3.html']

    inc_and_exc = [basename(f) for f in glob(f'{tmp_path}/bulk_md/inc_and_exc/*')]
    assert sorted(inc_and_exc) == ['b2.html', 'c3.html']


def test_markdown_rename_links(tmp_path):
    onto_tool.main([
        'bundle', '-v', 'output', f'{tmp_path}',
        'tests/bundle/rename_links.yaml'
    ])

    html_text = open(f'{tmp_path}/Links.html').read()
    # Relative .md links in <a> elements are renamed, preserving fragment and query
    assert 'href="other.html"' in html_text
    assert 'href="sub/page.html#section"' in html_text
    assert 'href="page.html?view=full"' in html_text
    # Absolute, root-relative and non-markdown links are untouched
    assert 'href="https://example.com/remote.md"' in html_text
    assert 'href="/docs/root.md"' in html_text
    assert 'href="mailto:someone@example.md"' in html_text
    assert 'href="image.png"' in html_text
    # Only href attributes on <a> elements are modified
    assert 'src="figure.md"' in html_text
    assert 'data-href="raw.md"' in html_text
    # HTML named entities are accepted by the parser
    assert '&#160;' in html_text


def test_markdown_no_rename_links():
    html_text = md2html('[Relative](other.md)', False).read()
    assert 'href="other.md"' in html_text


def test_markdown_rename_links_malformed():
    with pytest.raises(ValueError, match='not well-formed'):
        md2html('<div>unclosed <b>bold</div>', True)


def test_markdown_fenced_code_blocks():
    md = 'Example:\n\n```python\nif x < 2:\n    print("[link](other.md)")\n```\n'
    for rename in (False, True):
        html_text = md2html(md, rename).read()
        assert '<pre>' in html_text
        # Fence language is not rendered as text, and code is escaped
        assert '```' not in html_text
        assert '&lt;' in html_text
        # Markdown links inside code blocks are not converted to anchors
        assert '<a ' not in html_text


def test_markdown_highlight_css():
    html_text = md2html('```python\nx = 1\n```\n', False).read()
    style = html_text.split('<style>')[1].split('</style>')[0]
    # Pygments styles for the classes used in highlighted code blocks
    assert '.codehilite .k {' in style
    assert '<span class="n">x</span>' in html_text
