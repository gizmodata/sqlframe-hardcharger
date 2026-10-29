"""Servers from before the protocol was renamed to Chargewire keep working.

Servers released before the rename (Hardcharger 2.2.0 and older) serve the protocol's HTTP API
only under its old root, which code that calls that API directly (the tests) falls back to. The
driver handles the rest itself (adbc-driver-hardcharger 2.1.0 and newer). This file is the only
place that knows the old names.
"""

#: The protocol's HTTP root, and the name its discovery document announces, on a server
#: released before the rename.
LEGACY_ROOT = "/warp"
LEGACY_PROTOCOL = "warp-sql"
