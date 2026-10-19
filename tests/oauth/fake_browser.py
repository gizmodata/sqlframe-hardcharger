# Ported from gizmodata/hardcharger-adbc python/tests/fake_browser.py (Apache-2.0).
"""A stand-in for the user's browser in the browser sign-in tests, run by the driver with the
sign-in URL as its last argument: the identity provider "sends it back" to the server's
callback (the auth URL's redirect_uri) with the code given as the argument before it. (Not an
environment variable: the Go runtime in the driver library keeps the environment it started
with.)"""

import sys
import urllib.parse
import urllib.request

auth_url = sys.argv[-1]
params = urllib.parse.parse_qs(qs=urllib.parse.urlsplit(url=auth_url).query)
callback = params["redirect_uri"][0].replace("://localhost:", "://127.0.0.1:")
query = urllib.parse.urlencode(query={"code": sys.argv[-2], "state": params["state"][0]})
with urllib.request.urlopen(url=f"{callback}?{query}", timeout=10) as response:
    response.read()
