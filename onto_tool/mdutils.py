"""
Provides functionality for converting markdown files to other formats.

In the first instance this is to HTML5
The class md2html() has a template that calls bootstrap for styling
"""

import jinja2
import markdown
import io
import shutil


class Markdown2HTML:

    def __init__(self):
        self.TEMPLATE = """<!DOCTYPE html>
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

    def md2html(self, md):
        """
        Parameters:
        md (str): the markdown text that is to be converted to HTML5
        Returns:
        docfile (file object): a file object containing the HTML5
        """
        extensions = ['extra', 'smarty']
        html = markdown.markdown(md, extensions=extensions, output_format='html5')
        doc = jinja2.Template(self.TEMPLATE).render(content=html)
        docfile = io.StringIO(doc)
        return docfile


if __name__ == "__main__":
    test = """Release notes gist 9.1.0
--------------------------

* Reformatted all files to match uniform serialization.
* Corrected restriction for `gist:Collection`
* Provided missing labels for classes and properties.
* Corrected issues [72](https://github.com/semanticarts/gist/issues/72),
  [91](https://github.com/semanticarts/gist/issues/91), [95](https://github.com/semanticarts/gist/issues/95),
  [96](https://github.com/semanticarts/gist/issues/96), [97](https://github.com/semanticarts/gist/issues/97),
  [98](https://github.com/semanticarts/gist/issues/98), [101](https://github.com/semanticarts/gist/issues/101),
  [122](https://github.com/semanticarts/gist/issues/122), and [145](https://github.com/semanticarts/gist/issues/145).
* Removed outdated Visio and PDF files, documentation is now auto-generated as part of the release process.
* gistWiki has been removed.

Import URL: http://ontologies.semanticarts.com/o/gistCore9.1.0

Release notes gist 9.0.0
--------------------------
### General
*	The `gist` namespace has been modfied from `http:` to `https:`.
*	Added comments to ontologies.
*	Added labels and comments to many properties and classes.
*	`SocialBeing` has been removed.
*	The property `gist:party` has been renamed to `gist:hasParty`.

Import URL: http://ontologies.semanticarts.com/o/gistCore9.0.0
"""
    conv = Markdown2HTML()
    outLocation = "./outFile.html"
    f = conv.md2html(test)
    with open(outLocation, 'w') as fd:
        f.seek(0)
        shutil.copyfileobj(f, fd)
