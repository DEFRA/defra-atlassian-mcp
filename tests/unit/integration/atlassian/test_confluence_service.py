import httpx2
import pytest

from app.integration.atlassian import client as client_module
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models
from app.integration.atlassian.confluence import service as confluence_module
from tests.fakes import fake_oauth_client, httpx_helpers
from tests.fixtures import atlassian as vendor
from tests.support import app as test_app

_SPACES = httpx2.Response(200, json=vendor.space())
_NO_PAGES = httpx2.Response(200, json=vendor.content_search())


class _DenyingGuard(guard_module.SpaceGuard):
    def __init__(self) -> None:
        self.asked: list[tuple[str, str, models.Product]] = []

    async def check(
        self, user_id: str, space_key: str, product: models.Product
    ) -> None:
        self.asked.append((user_id, space_key, product))
        msg = "denied"
        raise guard_module.ForbiddenSpaceError(msg)


def _page(space_id: str = "9001", body: dict | None = None) -> httpx2.Response:
    return httpx2.Response(200, json=vendor.page(space_id=space_id, body=body))


def _make_service(responses, guard=None):
    http, transport = httpx_helpers.make_mock_client(responses)
    client = client_module.AtlassianClient(
        config=test_app.real_config(),
        client=http,
        oauth=fake_oauth_client.FakeOAuthClient("tok"),  # type: ignore[arg-type]
    )
    guard = guard or guard_module.AllowAllSpaceGuard()
    return confluence_module.ConfluenceService(client=client, guard=guard), transport


class TestListPages:
    async def test_scopes_the_cql_to_the_space(self):
        service, transport = _make_service([_NO_PAGES])

        await service.list_pages("usr_a", "FARM")

        cql = transport.requests[0].url.params["cql"]
        assert cql.startswith('space = "FARM" AND type = page')

    async def test_escapes_quotes_so_a_value_cannot_add_its_own_clause(self):
        service, transport = _make_service([_NO_PAGES])

        await service.list_pages("usr_a", "FARM", query='x" OR space = "SECRET')

        cql = transport.requests[0].url.params["cql"]
        assert 'text ~ "x\\" OR space = \\"SECRET"' in cql

    async def test_renders_id_and_title(self):
        pages = httpx2.Response(
            200, json=vendor.content_search({"id": "1", "title": "Intro"})
        )
        service, _ = _make_service([pages])

        assert await service.list_pages("usr_a", "FARM") == "1 Intro"

    async def test_checks_the_guard_before_calling_the_vendor(self):
        guard = _DenyingGuard()
        service, transport = _make_service([], guard=guard)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await service.list_pages("usr_a", "FARM")

        assert guard.asked == [("usr_a", "FARM", models.Product.CONFLUENCE)]
        assert transport.requests == []


class TestGetPage:
    async def test_renders_the_adf_body_sent_as_a_json_string(self):
        """Confluence returns the ADF document as a JSON string, unlike Jira
        which nests it as an object."""
        service, _ = _make_service(
            [_SPACES, _page(body=vendor.adf_document("Read this."))]
        )

        result = await service.get_page("usr_a", "FARM", "1")

        assert "# Onboarding" in result
        assert "Read this." in result

    async def test_refuses_a_page_that_lives_in_another_space(self):
        """The guard runs on the space key the caller named, so without this
        check naming a space you may read would hand you a page from one you
        may not."""
        service, _ = _make_service([_SPACES, _page(space_id="424242")])

        with pytest.raises(confluence_module.PageNotFoundError):
            await service.get_page("usr_a", "FARM", "1")

    async def test_reports_an_unknown_space_key(self):
        service, _ = _make_service([_NO_PAGES])

        with pytest.raises(confluence_module.SpaceNotFoundError):
            await service.get_page("usr_a", "NOSUCH", "1")

    async def test_checks_the_guard_before_calling_the_vendor(self):
        guard = _DenyingGuard()
        service, transport = _make_service([], guard=guard)

        with pytest.raises(guard_module.ForbiddenSpaceError):
            await service.get_page("usr_a", "FARM", "1")

        assert transport.requests == []
