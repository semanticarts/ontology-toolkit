import logging
import os
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml
from rdflib import Graph
from rdflib.namespace import RDF

from onto_tool import onto_tool
from onto_tool.bundle import BundleFileException


class RecordingHandler(SimpleHTTPRequestHandler):
    """
    Serves files from the tests directory, recording requested paths.

    /redirect/<path> redirects to /<path>, so redirects can be chained, and
    /latest redirects to /rdf-toolkit.jar, like a 'latest release' link.
    """
    requests = []

    def do_GET(self):
        RecordingHandler.requests.append(self.path)
        if self.path == '/latest':
            self.redirect('/rdf-toolkit.jar')
        elif self.path.startswith('/redirect/'):
            self.redirect(self.path[len('/redirect'):])
        else:
            super().do_GET()

    def redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def jar_server():
    RecordingHandler.requests = []
    handler = partial(RecordingHandler, directory=os.path.abspath('tests'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def write_bundle(tmp_path, jar, outputs):
    """Bundle with one transform action per output directory, using a remote jar."""
    bundle_file = tmp_path / 'bundle.yaml'
    bundle_file.write_text(yaml.safe_dump({
        'bundle': 'remote',
        'variables': {'jar_location': jar},
        'tools': [{
            'name': 'serializer',
            'type': 'Java',
            'jar': '{jar_location}',
            'arguments': ['-sfmt', 'turtle', '-tfmt', 'rdf-xml',
                          '-s', '{inputFile}', '-t', '{outputFile}']
        }],
        'actions': [{
            'action': 'transform',
            'tool': 'serializer',
            'source': 'tests/bundle',
            'includes': ['transform_sparql_data.ttl'],
            'rename': {'from': r'(.*)\.ttl', 'to': r'\g<1>.xml'},
            'target': str(output)
        } for output in outputs]
    }))
    return str(bundle_file)


def log_matches(caplog, pattern):
    """Return the first group of each log message matching pattern."""
    return [match.group(1) for match in
            (re.match(pattern, message) for message in caplog.messages)
            if match]


def downloaded_paths(caplog):
    return log_matches(caplog, r'Downloaded \S+ to (.*) \(\d+ bytes\)')


def removed_dirs(caplog):
    return log_matches(caplog, r'Removing downloaded tools in (.*)')


def test_remote_jar(caplog, tmp_path, jar_server):
    outputs = [tmp_path / 'first', tmp_path / 'second']
    bundle = write_bundle(tmp_path, f'{jar_server}/rdf-toolkit.jar', outputs)
    with caplog.at_level(logging.DEBUG):
        onto_tool.main(['bundle', '--debug', bundle])

    # Each action ran the downloaded tool
    for output in outputs:
        graph = Graph().parse(output / 'transform_sparql_data.xml', format='xml')
        assert len(list(graph.subject_objects(RDF.type))) == 2

    # Downloaded once for both actions, reported at debug level
    assert RecordingHandler.requests == ['/rdf-toolkit.jar']
    (jar_path,) = downloaded_paths(caplog)
    assert jar_path.endswith('rdf-toolkit.jar')
    # Download location is removed at the end of the run
    assert not os.path.exists(jar_path)
    (temp_dir,) = removed_dirs(caplog)
    assert jar_path.startswith(temp_dir)
    assert not os.path.exists(temp_dir)


def test_remote_jar_not_reported_without_debug(caplog, tmp_path, jar_server):
    bundle = write_bundle(tmp_path, f'{jar_server}/rdf-toolkit.jar', [tmp_path / 'out'])
    with caplog.at_level(logging.INFO):
        onto_tool.main(['bundle', bundle])

    assert (tmp_path / 'out' / 'transform_sparql_data.xml').exists()
    assert RecordingHandler.requests == ['/rdf-toolkit.jar']
    assert not any('Downloading' in message for message in caplog.messages)


def test_remote_jar_missing(caplog, tmp_path, jar_server):
    bundle = write_bundle(tmp_path, f'{jar_server}/missing.jar', [tmp_path / 'out'])
    with caplog.at_level(logging.DEBUG), \
            pytest.raises(BundleFileException, match='Unable to download .*missing.jar'):
        onto_tool.main(['bundle', '--debug', bundle])

    # Download location is removed even when the bundle fails
    (temp_dir,) = removed_dirs(caplog)
    assert not os.path.exists(temp_dir)


@pytest.mark.parametrize('path, expected_requests', [
    pytest.param('redirect/rdf-toolkit.jar',
                 ['/redirect/rdf-toolkit.jar', '/rdf-toolkit.jar'], id='single'),
    pytest.param('redirect/redirect/rdf-toolkit.jar',
                 ['/redirect/redirect/rdf-toolkit.jar', '/redirect/rdf-toolkit.jar',
                  '/rdf-toolkit.jar'], id='chained'),
    pytest.param('latest', ['/latest', '/rdf-toolkit.jar'], id='renamed'),
])
def test_remote_jar_redirect(caplog, tmp_path, jar_server, path, expected_requests):
    output = tmp_path / 'out'
    bundle = write_bundle(tmp_path, f'{jar_server}/{path}', [output])
    with caplog.at_level(logging.DEBUG):
        onto_tool.main(['bundle', '--debug', bundle])

    graph = Graph().parse(output / 'transform_sparql_data.xml', format='xml')
    assert len(list(graph.subject_objects(RDF.type))) == 2
    assert RecordingHandler.requests == expected_requests
    assert log_matches(caplog, r'Redirected \S+ to (\S+)') == [f'{jar_server}/rdf-toolkit.jar']
    # The jar is named after the final URL, not the redirecting one
    (jar_path,) = downloaded_paths(caplog)
    assert os.path.basename(jar_path) == 'rdf-toolkit.jar'


def test_remote_jar_redirect_missing(caplog, tmp_path, jar_server):
    bundle = write_bundle(tmp_path, f'{jar_server}/redirect/missing.jar', [tmp_path / 'out'])
    with caplog.at_level(logging.DEBUG), \
            pytest.raises(BundleFileException, match='Unable to download .*/redirect/missing.jar'):
        onto_tool.main(['bundle', '--debug', bundle])

    assert RecordingHandler.requests == ['/redirect/missing.jar', '/missing.jar']
