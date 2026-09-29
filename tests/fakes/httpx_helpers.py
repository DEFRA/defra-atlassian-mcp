import httpx2


class MockTransport(httpx2.AsyncBaseTransport):
    def __init__(self, responses: list[httpx2.Response | Exception]) -> None:
        self._queue = list(responses)
        self.requests: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if not self._queue:
            msg = "MockTransport: no more responses queued"
            raise RuntimeError(msg)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_mock_client(
    responses: list[httpx2.Response | Exception],
) -> tuple[httpx2.AsyncClient, MockTransport]:
    transport = MockTransport(responses)
    client = httpx2.AsyncClient(transport=transport)
    return client, transport
