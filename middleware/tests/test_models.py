import httpx


async def test_models_lists_allowed_models_in_openai_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert [m["id"] for m in body["data"]] == ["gpt-4o-mini", "gpt-4o"]
    assert all(m["object"] == "model" for m in body["data"])
