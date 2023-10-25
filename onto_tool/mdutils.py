"""
Provides functionality for converting markdown files to other formats.

In the first instance this is to HTML5
The class md2html() has a template that calls bootstrap for styling
"""

import io

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


def md2html(md):
    """
    Parameters:
    md (str): the markdown text that is to be converted to HTML5
    Returns:
    docfile (file object): a file object containing the HTML5
    """
    extensions = ['extra', 'smarty', 'tables']
    html = markdown2.markdown(md, extras=extensions)
    doc = jinja2.Template(_TEMPLATE).render(content=html)
    docfile = io.StringIO(doc)
    return docfile
