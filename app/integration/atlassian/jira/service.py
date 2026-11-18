import re
from typing import Any

from app.integration.atlassian import client as atlassian_client
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models
from app.integration.atlassian.content import adf

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100
_SEARCH_FIELDS = "summary,status,issuetype,assignee,updated"
_ISSUE_FIELDS = (
    "summary,status,issuetype,assignee,reporter,priority,updated,description,project"
)
# Anchored with \Z, not $, so a trailing newline cannot slip through. The key
# is interpolated into the request path, so anything beyond PROJECT-123 (a
# slash, a dot segment, a query string) must never reach the client.
_ISSUE_KEY = re.compile(r"(?P<project>[A-Z][A-Z0-9_]+)-[0-9]+\Z")


class IssueNotFoundError(Exception):
    """Raised when an issue key does not resolve to an issue."""


class JiraService:
    """Read-only Jira access, gated per project key.

    Every public method calls the guard first, before a token is fetched or
    any vendor call is made -- there is no path to Jira data that skips it.
    """

    def __init__(
        self,
        client: atlassian_client.AtlassianClient,
        guard: guard_module.SpaceGuard,
    ) -> None:
        self._client = client
        self._guard = guard

    async def search_issues(
        self,
        user_id: str,
        project_key: str,
        text: str | None = None,
        status: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> str:
        await self._guard.check(user_id, project_key, models.Product.JIRA)

        clauses = [f"project = {_quote(project_key)}"]
        if text:
            clauses.append(f"text ~ {_quote(text)}")
        if status:
            clauses.append(f"status = {_quote(status)}")

        jql = " AND ".join(clauses) + " ORDER BY updated DESC"

        payload = await self._client.get(
            user_id,
            models.Product.JIRA,
            "/rest/api/3/search/jql",
            params={
                "jql": jql,
                "maxResults": _clamp(limit),
                "fields": _SEARCH_FIELDS,
            },
        )

        issues = payload.get("issues", [])
        if not issues:
            return f"No issues matched in {project_key}."

        return "\n".join(_render_issue_line(issue) for issue in issues)

    async def get_issue(self, user_id: str, issue_key: str) -> str:
        """Fetch one issue.

        The guard runs on the project in the key's own prefix, before any
        vendor call. That is not enough on its own: Jira resolves the old key
        of a moved issue to the issue in its new project. So the project on
        the returned issue is compared with the one that was checked, and a
        mismatch is reported as not found rather than leaking the issue.
        """
        project_key = project_key_of(issue_key)
        await self._guard.check(user_id, project_key, models.Product.JIRA)

        payload = await self._client.get(
            user_id,
            models.Product.JIRA,
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": _ISSUE_FIELDS},
        )

        if _field(payload, "project", "key") != project_key:
            msg = f"{issue_key} is not an issue in {project_key}."
            raise IssueNotFoundError(msg)

        return _render_issue(payload)


def project_key_of(issue_key: str) -> str:
    """``FARM-123`` -> ``FARM``. Raises IssueNotFoundError for anything that
    is not exactly an issue key, so a malformed key never reaches the guard
    and a crafted one (``FARM-1/../OTHER-5``) never reaches the request
    path, where URL normalisation would address a different issue."""
    match = _ISSUE_KEY.match(issue_key)
    if match is None:
        msg = f"{issue_key} is not a Jira issue key (expected e.g. FARM-123)."
        raise IssueNotFoundError(msg)
    return match.group("project")


def _clamp(limit: int) -> int:
    return max(1, min(limit, _MAX_LIMIT))


def _quote(value: str) -> str:
    """Quote a JQL string literal. Both the backslash and the quote have to
    be escaped, in that order, or a crafted project name could close the
    literal and append its own clause."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _field(issue: dict[str, Any], *path: str) -> str:
    value: Any = issue.get("fields", {})
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return str(value) if value is not None else ""


def _render_issue_line(issue: dict[str, Any]) -> str:
    key = issue.get("key", "")
    summary = _field(issue, "summary")
    status = _field(issue, "status", "name")
    issue_type = _field(issue, "issuetype", "name")
    assignee = _field(issue, "assignee", "displayName") or "Unassigned"
    return f"{key} [{status}] ({issue_type}, {assignee}) {summary}"


def _render_issue(issue: dict[str, Any]) -> str:
    lines = [
        f"# {issue.get('key', '')} {_field(issue, 'summary')}",
        f"Status: {_field(issue, 'status', 'name')}",
        f"Type: {_field(issue, 'issuetype', 'name')}",
        f"Priority: {_field(issue, 'priority', 'name')}",
        f"Assignee: {_field(issue, 'assignee', 'displayName') or 'Unassigned'}",
        f"Reporter: {_field(issue, 'reporter', 'displayName')}",
        f"Updated: {_field(issue, 'updated')}",
    ]

    description = adf.render(issue.get("fields", {}).get("description"))
    if description:
        lines.extend(["", "## Description", description])

    return "\n".join(lines)
