"""Utility functions to execute SPARQL queries and unpack results."""
import re
from typing import Iterator
from urllib.parse import urlparse, urlunparse

from SPARQLWrapper import BASIC, CSV, JSON, POST, SPARQLWrapper


def create_endpoint(url, user=None, password=None) -> SPARQLWrapper:
    """Wrap specified endpoint with provided BasicAuth credentials."""
    repo_url = urlparse(url)

    sparql = SPARQLWrapper(urlunparse((repo_url.scheme,
                                       re.sub('^.*@', '', repo_url.netloc),
                                       repo_url.path,
                                       '', '', '')))

    sparql.setHTTPAuth(BASIC)
    sparql.setCredentials(user if user else repo_url.username,
                          password if password else repo_url.password)
    sparql.setMethod(POST)

    return sparql


def select_query(sparql: SPARQLWrapper, query: str) -> Iterator[dict]:
    """Execute SELECT query, returning each result row as dict."""
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    for result in results["results"]["bindings"]:
        yield dict(
            (v, result[v]["value"])
            for v in results["head"]["vars"] if v in result
        )


def select_query_csv(sparql: SPARQLWrapper, query: str) -> bytes:
    """Execute SELECT query, returning results as CSV text."""
    sparql.setQuery(query)
    sparql.setReturnFormat(CSV)
    results = sparql.query().convert()

    return results
