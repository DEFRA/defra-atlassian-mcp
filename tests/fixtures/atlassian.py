"""Atlassian Jira and Confluence API payload shapes -- the single owner of
this vendor contract. Import from here instead of redeclaring a payload dict
inline.

VERIFIED against tests/cassettes/atlassian_exchange_code.yaml for the OAuth
token response and the accessible-resources list. The Jira and Confluence
*content* shapes here are NOT cassette-backed: they are reduced to the fields
app/integration/atlassian/ actually reads, taken from the Atlassian REST v3
and Confluence v2 docs rather than from a recorded response. If you add a
payload without a cassette entry to match, say so in the same way.

Factories return the raw shape the vendor sends. Every factory accepts
`**overrides` -- never share a mutable instance between tests.
"""

import json
from typing import Any


def accessible_resources(cloud_id: str = "cloud-1") -> list[dict[str, Any]]:
    return [
        {
            "id": cloud_id,
            "url": "https://example.atlassian.net",
            "name": "example",
            "scopes": ["read:jira-work"],
        }
    ]


def oauth_token(**overrides: Any) -> dict[str, Any]:
    token = {
        "access_token": "example-access-token",
        "refresh_token": "example-refresh-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    token.update(overrides)
    return token


def me(**overrides: Any) -> dict[str, Any]:
    """GET /me. Note the snake_case account_id -- unlike the product APIs,
    which use accountId."""
    profile = {
        "account_id": "acc-1",
        "name": "Dev User",
        "email": "dev@example.com",
    }
    profile.update(overrides)
    return profile


def adf_document(text: str = "The gate is broken.") -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def issue(
    key: str = "FARM-1",
    *,
    summary: str = "Fix the gate",
    status: str = "Done",
    issue_type: str = "Bug",
    assignee: str | None = None,
    description: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": summary,
        "status": {"name": status},
        "issuetype": {"name": issue_type},
        "assignee": {"displayName": assignee} if assignee else None,
        "reporter": {"displayName": "Someone Else"},
        "priority": {"name": "High"},
        "updated": "2026-08-21T11:40:00.000+0000",
    }
    if description is not None:
        fields["description"] = description

    payload = {"key": key, "fields": fields}
    payload.update(overrides)
    return payload


def search_results(*issues: dict[str, Any]) -> dict[str, Any]:
    return {"issues": list(issues)}


def space(space_id: str = "9001", key: str = "FARM") -> dict[str, Any]:
    return {"results": [{"id": space_id, "key": key}]}


def page(
    page_id: str = "1",
    *,
    title: str = "Onboarding",
    space_id: str = "9001",
    body: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Confluence v2 returns the ADF body as a JSON *string*, unlike Jira
    which nests it as an object."""
    payload: dict[str, Any] = {
        "id": page_id,
        "title": title,
        "spaceId": space_id,
    }
    if body is not None:
        payload["body"] = {"atlas_doc_format": {"value": json.dumps(body)}}
    payload.update(overrides)
    return payload


def content_search(*pages: dict[str, Any]) -> dict[str, Any]:
    return {"results": list(pages)}
