import fastapi
import pytest
from fastapi.testclient import TestClient

from app.common import tracing


@pytest.fixture
def app_with_trace_middleware(fake_config):
    app = fastapi.FastAPI()
    app.add_middleware(tracing.TraceIdMiddleware, cfg=fake_config)

    @app.get("/probe")
    async def probe() -> dict[str, str | None]:
        return {
            "trace_id": tracing.ctx_trace_id.get(""),
            "method": tracing.ctx_request.get(None)
            and tracing.ctx_request.get()["method"],
        }

    return TestClient(app)


class TestTraceIdMiddleware:
    def test_propagates_header_to_context(self, app_with_trace_middleware, fake_config):
        response = app_with_trace_middleware.get(
            "/probe", headers={fake_config.tracing_header: "abc-123"}
        )
        assert response.status_code == 200
        assert response.json()["trace_id"] == "abc-123"

    def test_sets_request_context_without_header(self, app_with_trace_middleware):
        response = app_with_trace_middleware.get("/probe")
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "GET"
        # No header sent — ctx_trace_id was not set within this request scope
