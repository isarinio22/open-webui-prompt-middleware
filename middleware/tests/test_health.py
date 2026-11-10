import httpx
import respx


async def test_health_is_up_without_dependencies(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_upstream_answers(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.get("/models").respond(200, json={"object": "list", "data": []})

    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_not_ready_when_upstream_unreachable(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.get("/models").mock(side_effect=httpx.ConnectError("refused"))

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "upstream unreachable: ConnectError",
    }


async def test_not_ready_when_upstream_rejects_key(
    client: httpx.AsyncClient, upstream: respx.MockRouter
) -> None:
    upstream.get("/models").respond(401, json={"error": {"message": "bad key"}})

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "upstream returned HTTP 401"


async def test_ready_probe_is_cached(client: httpx.AsyncClient, upstream: respx.MockRouter) -> None:
    route = upstream.get("/models").respond(200, json={"object": "list", "data": []})

    await client.get("/ready")
    await client.get("/ready")

    assert route.call_count == 1
