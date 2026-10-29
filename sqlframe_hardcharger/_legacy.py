"""Drivers and servers from before the protocol was renamed to Chargewire keep working.

adbc-driver-hardcharger 2.0.2 and older take statement options only under the protocol's old
prefix (newer drivers take both spellings): :func:`legacy_statement_options` gives the options
to retry with when such a driver refuses ``adbc.chargewire.*``. Servers released before the
rename (Hardcharger 2.2.0 and older) serve the protocol's HTTP API only under its old root,
which code that calls that API directly (the tests) falls back to. This file is the only place
that knows the old names.
"""

from __future__ import annotations

import typing as t

_CURRENT_PREFIX = "adbc.chargewire."
_LEGACY_PREFIX = "adbc.warp."

#: The protocol's HTTP root, and the name its discovery document announces, on a server
#: released before the rename.
LEGACY_ROOT = "/warp"
LEGACY_PROTOCOL = "warp-sql"


def legacy_statement_options(options: t.Mapping[str, str]) -> t.Optional[t.Dict[str, str]]:
    """``options`` with every ``adbc.chargewire.*`` key under the old prefix, or None when no
    key has the current prefix (so there is nothing to retry)."""
    if not any(key.startswith(_CURRENT_PREFIX) for key in options):
        return None
    return {
        (_LEGACY_PREFIX + key[len(_CURRENT_PREFIX) :] if key.startswith(_CURRENT_PREFIX) else key): value
        for key, value in options.items()
    }
