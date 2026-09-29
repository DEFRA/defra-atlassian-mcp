"""Deliberately does NOT use tests/support/app.py's rest_client -- that
swaps every persistence port for a fake. This drives create_app(fake_config)
with no container override, i.e. the real build_async_container() the
production entrypoint uses, so it is the one place proving the real DI
graph and Mongo-lazy-resolution actually construct without error.
"""

import fastapi.testclient
import pytest

import app.entrypoints.http as main_mod


@pytest.fixture
def client(fake_config):
    with fastapi.testclient.TestClient(main_mod.create_app(fake_config)) as test_client:
        yield test_client


class TestHealth:
    def test_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
