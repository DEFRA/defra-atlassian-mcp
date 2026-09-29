"""The authenticated caller — the single currency between auth and handlers.

Both /mcp tools and the REST routers receive a Principal and never a raw
token. Unlike the mcp-template reference design (which maps an external IdP's
claims through a shared `from_claims` function), atlassian-mcp mints its own
personal access tokens: a verified token already resolves directly to a
stored User + PersonalAccessToken record, so there is no generic
claims-to-identity mapping step to centralise here. `Principal` is just the
shape both surfaces build, in one place each, once they have that record —
see app.infra.auth.personal_token (MCP) and
app.infra.rest.auth.resolver (REST).
"""

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class Principal:
    """A validated caller: who they are, plus the scopes they were granted."""

    user_id: str
    scopes: frozenset[str] = frozenset()
    # Optional profile, populated when the token/header carries it.
    email: str | None = None
    label: str | None = None  # the presented PAT's label, e.g. "Claude Code"
    token_id: str | None = None  # the presented PAT's id, for audit/revoke UX

    def has_scope(self, scope: str) -> bool:
        """Whether the caller was granted `scope` (for per-operation checks)."""
        return scope in self.scopes
