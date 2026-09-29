"""RFC 7636 PKCE (S256) for the Atlassian OAuth 2.0 (3LO) code exchange.

Generated and verified entirely server-side: the portal only ever sees the
authorization URL (which carries the derived code_challenge) and relays
{code, state} back on the callback. The verifier itself lives only in
OAuthStateStore, alongside the state it was issued with, and is never sent
to the portal.
"""

import base64
import hashlib
import secrets

_VERIFIER_ENTROPY_BYTES = 32


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(_VERIFIER_ENTROPY_BYTES)


def derive_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
