import httpx2
import pytest

from app.integration.atlassian import client as client_module
from app.integration.atlassian import guard as guard_module
from app.integration.atlassian import models
from app.integration.atlassian.confluence import service as confluence_module
from app.integration.linking import oauth_auth
from tests.fakes import fake_oauth_client, httpx_helpers
from tests.fixtures import atlassian as vendor

_SPACES = httpx2.Response(200, json=vendor.space())
_NO_PAGES = httpx2.Response(200, json=vendor.content_search())


class _DenyingPolicy:
    """Records what it was asked, and always says no -- so a service that
    called the vendor before the policy would fail on an unconsumed
    response."""

    def __init__(self) -> None:
        self.asked: list[tuple[models.Product, str]] = []

    async def check(self, product: models.Product, key: str) -> None:
        self.asked.append((product, key))
        msg = "denied"
        raise guard_module.ForbiddenResourceError(msg)


def _page(space_id: str = "9001", body: dict | None = None) -> httpx2.Response:
    return httpx2.Response(200, json=vendor.page(space_id=space_id, body=body))


class _PermittingPolicy:
    """Test-only: says yes to everything, so these tests cover what the
    service sends and renders. Policy behaviour is tested in test_guard.py,
    and the shipped code has no allow-everything policy."""

    async def check(
        self,
        product: models.Product,  # noqa: ARG002
        key: str,  # noqa: ARG002
    ) -> None:
        return None


def _make_service(responses, policy=None):
    http, transport = httpx_helpers.make_mock_client(responses)
    auth = oauth_auth.OAuthAtlassianAuth(
        "usr_a",
        fake_oauth_client.FakeOAuthClient("tok"),
        "https://api.atlassian.com",
    )
    client = client_module.AtlassianClient(http=http, auth=auth)
    policy = policy or _PermittingPolicy()
    return confluence_module.ConfluenceService(client=client, policy=policy), transport


class TestListPages:
    async def test_scopes_the_cql_to_the_space(self):
        service, transport = _make_service([_NO_PAGES])

        await service.list_pages("FARM")

        cql = transport.requests[0].url.params["cql"]
        assert cql.startswith('space = "FARM" AND type = page')

    async def test_escapes_quotes_so_a_value_cannot_add_its_own_clause(self):
        service, transport = _make_service([_NO_PAGES])

        await service.list_pages("FARM", query='x" OR space = "SECRET')

        cql = transport.requests[0].url.params["cql"]
        assert 'text ~ "x\\" OR space = \\"SECRET"' in cql

    async def test_renders_id_and_title(self):
        pages = httpx2.Response(
            200, json=vendor.content_search({"id": "1", "title": "Intro"})
        )
        service, _ = _make_service([pages])

        assert await service.list_pages("FARM") == "1 Intro"

    async def test_checks_the_policy_before_calling_the_vendor(self):
        policy = _DenyingPolicy()
        service, transport = _make_service([], policy=policy)

        with pytest.raises(guard_module.ForbiddenResourceError):
            await service.list_pages("FARM")

        assert policy.asked == [(models.Product.CONFLUENCE, "FARM")]
        assert transport.requests == []


class TestGetPage:
    async def test_renders_the_adf_body_sent_as_a_json_string(self):
        """Confluence returns the ADF document as a JSON string, unlike Jira
        which nests it as an object."""
        service, _ = _make_service(
            [_SPACES, _page(body=vendor.adf_document("Read this."))]
        )

        result = await service.get_page("FARM", "1")

        assert "# Onboarding" in result
        assert "Read this." in result

    async def test_refuses_a_page_that_lives_in_another_space(self):
        """The policy runs on the space key the caller named, so without this
        check naming a space you may read would hand you a page from one you
        may not."""
        service, _ = _make_service([_SPACES, _page(space_id="424242")])

        with pytest.raises(confluence_module.PageNotFoundError):
            await service.get_page("FARM", "1")

    @pytest.mark.parametrize(
        "page_id",
        ["1/../2", "../spaces", "1?x=y", "", "abc", "１２"],
    )
    async def test_refuses_a_page_id_that_is_not_digits(self, page_id):
        """The id is interpolated into the request path, so anything but
        digits could address another resource."""
        service, transport = _make_service([])

        with pytest.raises(confluence_module.PageNotFoundError):
            await service.get_page("FARM", page_id)

        assert transport.requests == []

    async def test_reports_an_unknown_space_key(self):
        service, _ = _make_service([_NO_PAGES])

        with pytest.raises(confluence_module.SpaceNotFoundError):
            await service.get_page("NOSUCH", "1")

    async def test_checks_the_policy_before_calling_the_vendor(self):
        policy = _DenyingPolicy()
        service, transport = _make_service([], policy=policy)

        with pytest.raises(guard_module.ForbiddenResourceError):
            await service.get_page("FARM", "1")

        assert transport.requests == []
