import os

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
# A local model can take several minutes for a multi-specialist workflow.
CHAT_TIMEOUT_SECONDS = 600.0


def send_chat_message(message: str, session_id: str | None) -> dict:
    """Send one chat message to FastAPI and return its JSON response."""
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    with httpx.Client(timeout=CHAT_TIMEOUT_SECONDS) as client:
        response = client.post(f"{API_BASE_URL}/chat", json=payload)
        response.raise_for_status()
        return response.json()


def describe_http_error(exc: httpx.HTTPStatusError) -> str:
    """Return a useful API error without exposing backend implementation data."""
    try:
        detail = exc.response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None

    return detail or f"The API returned HTTP {exc.response.status_code}."


def show_message(
    role: str,
    content: str,
    agents_used: list[str] | None = None,
    tools_called: list[str] | None = None,
) -> None:
    """Display one user or assistant message."""
    with st.chat_message(role):
        st.markdown(content)
        if agents_used:
            st.caption("Agents: " + " -> ".join(agents_used))
        if tools_called:
            st.caption("Tools: " + " -> ".join(tools_called))


def render_app() -> None:
    """Render the Streamlit chat interface."""
    st.set_page_config(
        page_title="Multi-Agent Architecture Advisor",
        page_icon=":building_construction:",
    )
    st.title("Multi-Agent Architecture Advisor")
    st.caption("Local architecture guidance from coordinated specialist agents.")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = None

    with st.sidebar:
        if st.button("New conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.session_id = None
            st.rerun()

        if st.session_state.session_id:
            st.caption(f"Session: {st.session_state.session_id}")

    for message in st.session_state.messages:
        show_message(
            role=message["role"],
            content=message["content"],
            agents_used=message.get("agents_used"),
            tools_called=message.get("tools_called"),
        )

    prompt = st.chat_input("Ask about a cloud architecture or internal requirement")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    show_message("user", prompt)

    with st.chat_message("assistant"):
        with st.spinner("Consulting the specialist agents..."):
            try:
                result = send_chat_message(prompt, st.session_state.session_id)
            except httpx.HTTPStatusError as exc:
                st.error(describe_http_error(exc))
                return
            except httpx.TimeoutException:
                st.error(
                    "The request took longer than 10 minutes. "
                    "The API may still be processing it; try again shortly."
                )
                return
            except httpx.HTTPError:
                st.error("Could not reach the API. Confirm that `make api` is running.")
                return

        answer = result["answer"]
        agents_used = result.get("agents_used", [])
        tools_called = result.get("tools_called", [])
        st.markdown(answer)
        if agents_used:
            st.caption("Agents: " + " -> ".join(agents_used))
        if tools_called:
            st.caption("Tools: " + " -> ".join(tools_called))

    st.session_state.session_id = result["session_id"]
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "agents_used": agents_used,
            "tools_called": tools_called,
        }
    )


if __name__ == "__main__":
    render_app()
