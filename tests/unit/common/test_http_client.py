from app.common import http_client


class TestCreateAsyncClient:
    def test_bakes_trace_id_into_headers(self, fake_config):
        client = http_client.create_async_client(
            tracing_header=fake_config.tracing_header,
            trace_id="trace-id-value",
        )

        assert client.headers[fake_config.tracing_header] == "trace-id-value"

    def test_omits_header_when_trace_id_missing(self, fake_config):
        client = http_client.create_async_client(
            tracing_header=fake_config.tracing_header,
            trace_id=None,
        )

        assert fake_config.tracing_header not in client.headers


class TestCreateClient:
    def test_bakes_trace_id_into_headers(self, fake_config):
        client = http_client.create_client(
            tracing_header=fake_config.tracing_header,
            trace_id="trace-id-value",
        )

        assert client.headers[fake_config.tracing_header] == "trace-id-value"
