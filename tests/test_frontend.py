from unittest.mock import patch

import httpx
import pytest

from multi_agent_project.frontend import streamlit_app


@pytest.mark.parametrize(
    ("session_id", "expected_payload"),
    [
        (None, {"message": "Hello"}),
        ("session-1", {"message": "Hello", "session_id": "session-1"}),
    ],
)
def test_send_chat_message(session_id, expected_payload) -> None:
    expected_response = {
        "answer": "Hi",
        "session_id": "session-1",
        "agents_used": ["architecture_coordinator"],
        "tools_called": ["researcher.search_web"],
    }

    with patch(
        "multi_agent_project.frontend.streamlit_app.httpx.Client"
    ) as client_class:
        client = client_class.return_value.__enter__.return_value
        client.post.return_value.json.return_value = expected_response

        result = streamlit_app.send_chat_message("Hello", session_id)

    assert result == expected_response
    client_class.assert_called_once_with(timeout=600.0)
    client.post.assert_called_once_with(
        "http://127.0.0.1:8001/chat",
        json=expected_payload,
    )
    client.post.return_value.raise_for_status.assert_called_once_with()


def test_describe_http_error_uses_api_detail() -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8001/chat")
    response = httpx.Response(
        503,
        json={"detail": "The agent service is temporarily unavailable."},
        request=request,
    )
    error = httpx.HTTPStatusError(
        "Service unavailable",
        request=request,
        response=response,
    )

    assert streamlit_app.describe_http_error(error) == (
        "The agent service is temporarily unavailable."
    )
