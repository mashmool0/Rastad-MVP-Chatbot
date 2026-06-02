import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_message_returns_required_fields(client):
    """Valid message → 200 with all expected response fields."""
    response = client.post(
        "/api/message",
        data={"name": "Ali", "message": "خدمات VIP راستاد چیه؟"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    for field in ("reply", "intent", "user_segment", "needs_human_support",
                  "confidence", "chunks_used", "llm_provider", "fallback_used", "latency_ms"):
        assert field in body, f"missing field: {field}"
    assert body["llm_provider"] == "mock"


@pytest.mark.django_db
def test_empty_message_rejected(client):
    """Empty message string → 400 Bad Request."""
    response = client.post(
        "/api/message",
        data={"name": "Ali", "message": ""},
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_missing_message_rejected(client):
    """Missing message field entirely → 400 Bad Request."""
    response = client.post(
        "/api/message",
        data={"name": "Ali"},
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_support_request_needs_human(client):
    """Message with payment/support keyword → needs_human_support=True."""
    response = client.post(
        "/api/message",
        data={"name": "Sara", "message": "مشکل پرداخت دارم"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["needs_human_support"] is True


@pytest.mark.django_db
def test_users_endpoint(client):
    """GET /api/users → 200 with a list."""
    response = client.get("/api/users")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.django_db
def test_user_messages_endpoint(client):
    """After sending a message, GET /api/users/{id}/messages returns it."""
    # Create a user by sending a message first
    post_resp = client.post(
        "/api/message",
        data={"name": "Reza", "message": "سلام"},
        content_type="application/json",
    )
    assert post_resp.status_code == 200

    # Fetch users to get the assigned user_id
    users_resp = client.get("/api/users")
    user_id = users_resp.json()[0]["user_id"]

    msgs_resp = client.get(f"/api/users/{user_id}/messages")
    assert msgs_resp.status_code == 200
    messages = msgs_resp.json()
    assert len(messages) >= 1
    assert messages[0]["intent"] is not None
