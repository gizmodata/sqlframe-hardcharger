# Ported from gizmodata/hardcharger-adbc python/tests/fake_browser.py (Apache-2.0).
"""A stand-in for the user's browser in the browser sign-in tests, run by the driver with the
sign-in URL as its last argument. It opens the URL and follows the identity provider's redirect
back to the server's callback, as a browser does after the user signs in. The argument before
the URL is the code the mock identity provider hands out (``mock_code``: "code-ok..." it then
accepts, anything else it refuses). (Not an environment variable: the Go runtime in the driver
library keeps the environment it started with.) ``--count FILE`` first appends a line to FILE,
so tests can count the sign-ins."""

import sys
import urllib.parse
import urllib.request

if "--count" in sys.argv:  # --count FILE: append a line per sign-in, for the tests to count
    with open(file=sys.argv[sys.argv.index("--count") + 1], mode="a", encoding="utf-8") as count:
        count.write("sign-in\n")
auth_url = sys.argv[-1] + "&" + urllib.parse.urlencode(query={"mock_code": sys.argv[-2]})
with urllib.request.urlopen(url=auth_url, timeout=10) as response:  # follows the redirect
    response.read()
