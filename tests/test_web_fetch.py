from unittest.mock import patch

import httpx
import pytest

from multi_agent_project.tools.web_fetch import fetch_web_page, validate_public_url

URL = "https://example.com/docs"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch) -> None:
    """Resolve test hostnames to a public address without using live DNS."""
    monkeypatch.setattr(
        "multi_agent_project.tools.web_fetch.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ],
    )


def test_fetch_extracts_page_text() -> None:
    """Extract readable text while removing scripts, styles, nav, and footers."""
    response = httpx.Response(
        200,
        text=(
            "<html><body><nav>Menu</nav><style>CSS</style>"
            "<h1>Documentation</h1><p>Cloud <b>architecture</b>.</p>"
            "<script>JavaScript</script><footer>Copyright</footer></body></html>"
        ),
        request=httpx.Request("GET", URL),
    )
    with patch("multi_agent_project.tools.web_fetch.httpx.Client") as client_class:
        client = client_class.return_value.__enter__.return_value
        client.get.return_value = response

        result = fetch_web_page(URL)

    assert result == {
        "status": "success",
        "url": URL,
        "content": "Documentation Cloud architecture .",
    }
    client_class.assert_called_once_with(timeout=10.0, follow_redirects=False)
    client.get.assert_called_once_with(URL)


def test_fetch_limits_content_length() -> None:
    """Limit extracted page content to 12,000 characters."""
    response = httpx.Response(
        200,
        text="<p>" + "x" * 12001 + "</p>",
        request=httpx.Request("GET", URL),
    )
    with patch("multi_agent_project.tools.web_fetch.httpx.Client") as client_class:
        client_class.return_value.__enter__.return_value.get.return_value = response
        result = fetch_web_page(URL)

    assert result["status"] == "success"
    assert result["content"] == "x" * 12000


@pytest.mark.parametrize("status_code", [302, 404, 500])
def test_fetch_returns_http_error(status_code: int) -> None:
    """Return an error for redirects and unsuccessful HTTP responses."""
    response = httpx.Response(status_code, request=httpx.Request("GET", URL))
    with patch("multi_agent_project.tools.web_fetch.httpx.Client") as client_class:
        client_class.return_value.__enter__.return_value.get.return_value = response
        result = fetch_web_page(URL)

    assert result["status"] == "error"
    assert result["url"] == URL
    assert str(status_code) in result["error"]
    assert "content" not in result


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_fetch_returns_transport_error(error_type: type[httpx.HTTPError]) -> None:
    """Return a structured error for connection failures and read timeouts."""
    with patch("multi_agent_project.tools.web_fetch.httpx.Client") as client_class:
        client_class.return_value.__enter__.return_value.get.side_effect = error_type(
            "Connection unavailable", request=httpx.Request("GET", URL)
        )
        result = fetch_web_page(URL)

    assert result == {
        "status": "error",
        "url": URL,
        "error": "Connection unavailable",
    }


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://service.localhost/admin",
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://10.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "https://user:password@example.com/docs",
        "https://example.com:8443/docs",
    ],
)
def test_fetch_rejects_unsafe_urls_without_making_request(url: str) -> None:
    with patch("multi_agent_project.tools.web_fetch.httpx.Client") as client_class:
        result = fetch_web_page(url)

    assert result["status"] == "error"
    assert result["url"] == url
    client_class.assert_not_called()


def test_validate_public_url_rejects_hostname_resolving_to_private_ip(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "multi_agent_project.tools.web_fetch.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("192.168.1.10", 443)),
        ],
    )

    with pytest.raises(ValueError, match="Local, private, and reserved"):
        validate_public_url(URL)
