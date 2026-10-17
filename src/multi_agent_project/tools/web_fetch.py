import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}


class UnsafeURLError(ValueError):
    """Raised when a URL could access a non-public network destination."""


def validate_public_url(url: str) -> None:
    """Reject URLs that could target local, private, or reserved networks."""
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("Invalid URL") from exc

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URLs containing credentials are not allowed")
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError("Only ports 80 and 443 are allowed")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURLError("Local network destinations are not allowed")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        addresses = [literal_ip]
    else:
        try:
            address_info = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeURLError("URL hostname could not be resolved") from exc

        addresses = [ipaddress.ip_address(item[4][0]) for item in address_info]

    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeURLError("Local, private, and reserved networks are not allowed")


def fetch_web_page(url: str) -> dict:
    """Fetch and extract text from a public web page.

    Args:
        url: URL of the public page to retrieve.

    Returns:
        Status and original URL, plus extracted text on success or an error
        message for unsafe URLs, HTTP errors, and transport failures. Only
        public HTTP(S) destinations on ports 80 and 443 are allowed. Text is
        limited to 12,000 characters; scripts, styles, navigation, and footers
        are removed. Requests time out after 10 seconds and redirects are not
        followed.
    """
    try:
        validate_public_url(url)

        with httpx.Client(
            timeout=10.0,
            follow_redirects=False,
        ) as client:
            response = client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        return {
            "status": "success",
            "url": url,
            "content": text[:12000],
        }

    except (httpx.HTTPError, UnsafeURLError) as exc:
        return {
            "status": "error",
            "url": url,
            "error": str(exc),
        }
