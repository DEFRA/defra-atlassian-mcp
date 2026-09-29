"""Our own token-verification port, so surfaces don't depend on FastMCP.

TokenVerifier is the seam both /mcp and the REST surface target: hand it a
bearer token, get back a VerifiedToken (validated claims) or None if the
token is not acceptable. atlassian-mcp mints its own personal access tokens
rather than validating an external IdP's signature, so the concrete binding
is a Mongo lookup — it lives in app.infra.auth.personal_token. Nothing
outside that adapter (and its two thin per-surface wrappers,
app.infra.mcp.auth and app.infra.rest.auth.resolver) needs to import FastMCP
or know how verification actually happens.
"""

import dataclasses
from typing import Any, Protocol


@dataclasses.dataclass(frozen=True, slots=True)
class VerifiedToken:
    """A token the verifier accepted, and the claims it carries."""

    claims: dict[str, Any]


class TokenVerifier(Protocol):
    """Validates a bearer token, returning None if it is not acceptable."""

    async def verify(self, token: str) -> VerifiedToken | None: ...
