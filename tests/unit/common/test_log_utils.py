import logging

from app.common import log_utils, tracing


def _make_record(msg: str = "test message") -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )


class TestExtraFieldsFilter:
    def test_with_all_context(self):
        trace_token = tracing.ctx_trace_id.set("test-trace-id")
        request_token = tracing.ctx_request.set(
            {"url": "http://test.com", "method": "GET"}
        )
        response_token = tracing.ctx_response.set({"status_code": 200})
        try:
            record = _make_record()
            result = log_utils.ExtraFieldsFilter().filter(record)
        finally:
            tracing.ctx_trace_id.reset(trace_token)
            tracing.ctx_request.reset(request_token)
            tracing.ctx_response.reset(response_token)

        assert result is True
        assert record.trace == {"id": "test-trace-id"}
        assert record.url == {"full": "http://test.com"}
        assert record.http == {
            "request": {"method": "GET"},
            "response": {"status_code": 200},
        }

    def test_with_no_context(self):
        record = _make_record()
        result = log_utils.ExtraFieldsFilter().filter(record)

        assert result is True
        assert not hasattr(record, "trace")
        assert not hasattr(record, "url")
        assert not hasattr(record, "http")


class TestEndpointFilter:
    def test_blocks_matching_path(self):
        filter_path = "/health"
        log_filter = log_utils.EndpointFilter(path=filter_path)
        record = _make_record(f"GET {filter_path} HTTP/1.1")

        assert log_filter.filter(record) is False

    def test_allows_non_matching_path(self):
        filter_path = "/health"
        log_filter = log_utils.EndpointFilter(path=filter_path)
        record = _make_record("GET /api/users HTTP/1.1")

        assert log_filter.filter(record) is True
