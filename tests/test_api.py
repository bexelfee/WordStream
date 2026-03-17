"""Core API tests: health, documents list, text document, progress."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_config(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert "hf_token_configured" in data
    assert isinstance(data["hf_token_configured"], bool)


@pytest.mark.asyncio
async def test_list_documents_empty(client):
    r = await client.get("/api/documents")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_text_document_and_list(client):
    r = await client.post(
        "/api/documents/text",
        json={"title": "Test Doc", "author": "Tester", "text": "One two three four five."},
    )
    assert r.status_code == 200
    doc = r.json()
    assert doc["title"] == "Test Doc"
    assert doc["word_count"] == 5
    assert doc["id"] is not None
    doc_id = doc["id"]

    r2 = await client.get("/api/documents")
    assert r2.status_code == 200
    list_data = r2.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == doc_id
    assert list_data[0]["word_count"] == 5
    assert "transcription_error" in list_data[0]


@pytest.mark.asyncio
async def test_get_and_update_progress(client):
    r = await client.post(
        "/api/documents/text",
        json={"title": "Progress Doc", "text": "Word one. Word two. Word three."},
    )
    assert r.status_code == 200
    doc_id = r.json()["id"]

    r_get = await client.get(f"/api/documents/{doc_id}/progress")
    assert r_get.status_code == 200
    prog = r_get.json()
    assert prog["current_word_index"] == 0
    assert prog["word_count"] >= 5  # tokenizer-dependent

    r_put = await client.put(
        f"/api/documents/{doc_id}/progress",
        json={"current_word_index": 2},
    )
    assert r_put.status_code == 200
    assert r_put.json()["current_word_index"] == 2

    r_get2 = await client.get(f"/api/documents/{doc_id}/progress")
    assert r_get2.status_code == 200
    assert r_get2.json()["current_word_index"] == 2
    assert r_get2.json()["word_count"] == prog["word_count"]


@pytest.mark.asyncio
async def test_get_content(client):
    r = await client.post(
        "/api/documents/text",
        json={"title": "Content Doc", "text": "Hello world."},
    )
    assert r.status_code == 200
    doc_id = r.json()["id"]

    r_content = await client.get(f"/api/documents/{doc_id}/content")
    assert r_content.status_code == 200
    data = r_content.json()
    assert data["processing"] is False
    assert "processing_error" in data
    assert "Hello" in data["text"] and "world" in data["text"]
