import re
from urllib.parse import urlparse, urlunparse

from SPARQLWrapper import SPARQLWrapper, POST, BASIC


def create_endpoint(url, user=None, password=None) -> SPARQLWrapper:
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
