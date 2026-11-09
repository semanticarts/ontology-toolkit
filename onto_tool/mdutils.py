"""
Provides functionality for converting markdown files to other formats.

In the first instance this is to HTML5
The class md2html() has a template that calls bootstrap for styling
"""

import io
import xml.etree.ElementTree as ET
from html.entities import name2codepoint
from urllib.parse import urlsplit, urlunsplit

import jinja2
import markdown2


_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <link href="http://netdna.bootstrapcdn.com/twitter-bootstrap/2.3.0/css/bootstrap-combined.min.css" rel="stylesheet">
    <style>
        body {
            font-family: sans-serif;
        }
        code, pre {
            font-family: monospace;
        }
        h1 code,
        h2 code,
        h3 code,
        h4 code,
        h5 code,
        h6 code {
            font-size: inherit;
        }
    </style>
</head>
<body>
<div class="container">
{{content}}
</div>
</body>
</html>
"""

_WRAPPER_START = '<div>'
_WRAPPER_END = '</div>'
# Referencing an external DTD (never fetched) makes the parser resolve
# undefined entities via XMLParser.entity rather than rejecting them
_XHTML_DOCTYPE = ('<!DOCTYPE div PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
                  '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">')


def _rename_md_url(href: str) -> str:
    """
    Replace a .md suffix with .html on a relative URL, preserving query and fragment.
    Absolute and root-relative (leading /) URLs are left unchanged.
    """
    url = urlsplit(href)
    if url.scheme or url.netloc or url.path.startswith('/') or not url.path.lower().endswith('.md'):
        return href
    return urlunsplit(url._replace(path=url.path[:-3] + '.html'))


def _rename_md_links(html: str) -> str:
    """
    Parse the HTML fragment, rename relative .md links in <a> elements to .html,
    and serialize it back to HTML.

    Raises ValueError if the HTML is not well-formed.
    """
    parser = ET.XMLParser()
    # Allow HTML named entities (e.g. &nbsp;) which are not predefined in XML
    parser.entity.update((name, chr(code)) for name, code in name2codepoint.items())
    try:
        parser.feed(_XHTML_DOCTYPE + _WRAPPER_START + html + _WRAPPER_END)
        root = parser.close()
    except ET.ParseError as e:
        raise ValueError(f'Converted HTML is not well-formed: {e}') from e

    for anchor in root.iter('a'):
        href = anchor.get('href')
        if href is not None:
            anchor.set('href', _rename_md_url(href))

    # ASCII encoding keeps non-ASCII characters as character references
    serialized = ET.tostring(root, encoding='us-ascii', method='html').decode('ascii')
    return serialized[len(_WRAPPER_START):-len(_WRAPPER_END)]


def md2html(md: str, renameLinks: bool):
    """
    Parameters:
    md (str): the markdown text that is to be converted to HTML5
    renameLins (bool): If true, rename relative links from .md to .html
    Returns:
    docfile (file object): a file object containing the HTML5
    """
    extensions = ['extra', 'smarty', 'tables']
    html = markdown2.markdown(md, extras=extensions)
    if renameLinks:
        html = _rename_md_links(html)
    doc = jinja2.Template(_TEMPLATE).render(content=html)
    docfile = io.StringIO(doc)
    return docfile
