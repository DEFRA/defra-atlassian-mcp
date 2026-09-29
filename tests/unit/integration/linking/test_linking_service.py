import unittest.mock

import pytest

from app.integration.linking import exceptions, models, oauth_client, service
from tests.fakes import in_memory_oauth_state_store, in_memory_token_store


def _make_oauth_mock() -> unittest.mock.NonCallableMock:
    """Autospec'd against OAuthClient so sync methods (build_authorization_url)
    and async methods (exchange_code) are mocked correctly -- a plain
    AsyncMock() would wrap every attribute as async, including sync ones."""
    return unittest.mock.create_autospec(oauth_client.OAuthClient, instance=True)


def _make_service(
    oauth: unittest.mock.NonCallableMock,
) -> tuple[
    service.LinkingService,
    in_memory_token_store.InMemoryTokenStore,
    in_memory_oauth_state_store.InMemoryOAuthStateStore,
]:
    tokens = in_memory_token_store.InMemoryTokenStore()
    states = in_memory_oauth_state_store.InMemoryOAuthStateStore()
    return (
        service.LinkingService(oauth=oauth, tokens=tokens, states=states),
        tokens,
        states,
    )


class TestGetAuthorizationUrl:
    async def test_issues_state_and_returns_authorization_url(self) -> None:
        oauth = _make_oauth_mock()
        oauth.build_authorization_url.side_effect = lambda state, code_challenge: (
            f"https://app.atlassian.co/authorize?state={state}&challenge={code_challenge}"
        )
        linking, _tokens, states = _make_service(oauth)

        url = await linking.get_authorization_url("user-123")

        assert url.startswith("https://app.atlassian.co/authorize?state=")
        issued_state = url.split("state=")[1].split("&")[0]
        # The state was consumed by build_authorization_url's caller only in
        # spirit -- issue() doesn't consume, so it should still resolve here.
        oauth_state = await states.consume(issued_state)
        assert oauth_state.user_id == "user-123"

    async def test_passes_the_code_challenge_through(self) -> None:
        oauth = _make_oauth_mock()
        oauth.build_authorization_url.return_value = (
            "https://app.atlassian.co/authorize"
        )
        linking, _tokens, _states = _make_service(oauth)

        await linking.get_authorization_url("user-123")

        oauth.build_authorization_url.assert_called_once()
        state, code_challenge = oauth.build_authorization_url.call_args.args
        assert state
        assert code_challenge


class TestCompleteConnection:
    async def test_exchanges_code_and_stores_token(self) -> None:
        oauth = _make_oauth_mock()
        token = models.AtlassianToken(access_token="a", refresh_token="b")
        oauth.exchange_code.return_value = token
        linking, tokens, states = _make_service(oauth)
        issued = await states.issue("user-123")

        await linking.complete_connection("user-123", "auth-code", issued.state)

        oauth.exchange_code.assert_awaited_once()
        code, code_verifier = oauth.exchange_code.await_args.args
        assert code == "auth-code"
        assert code_verifier
        assert await tokens.get_tokens("user-123") == token

    async def test_raises_on_user_mismatch(self) -> None:
        oauth = _make_oauth_mock()
        linking, tokens, states = _make_service(oauth)
        issued = await states.issue("user-123")

        with pytest.raises(exceptions.LinkMismatchError):
            await linking.complete_connection("someone-else", "auth-code", issued.state)

        oauth.exchange_code.assert_not_called()
        assert await tokens.get_tokens("user-123") is None

    async def test_propagates_unknown_state_error(self) -> None:
        oauth = _make_oauth_mock()
        linking, _tokens, _states = _make_service(oauth)

        with pytest.raises(exceptions.OAuthStateError):
            await linking.complete_connection(
                "user-123", "auth-code", "not-a-real-state"
            )

        oauth.exchange_code.assert_not_called()


class TestDisconnect:
    async def test_removes_stored_token(self) -> None:
        oauth = _make_oauth_mock()
        linking, tokens, _states = _make_service(oauth)
        await tokens.store_tokens(
            "user-123", models.AtlassianToken(access_token="a", refresh_token="b")
        )

        await linking.disconnect("user-123")

        assert await tokens.get_tokens("user-123") is None
