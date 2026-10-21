import ipaddress
import logging
import socket
from typing import Optional, Set
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cloud metadata endpoints and hostnames to block
BLOCKED_METADATA_HOSTS = {
    "169.254.169.254",
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}

# Standard GitHub domains for repository operations
GITHUB_ALLOWED_HOSTS = {
    "github.com",
    "www.github.com",
    "api.github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
}


class SSRFValidationError(Exception):
    """Raised when a URL violates SSRF safety constraints."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def is_ip_blocked(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Evaluates whether an IP address belongs to loopback, private, link-local,
    multicast, reserved, or cloud metadata ranges.
    """
    # IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        return is_ip_blocked(ip_obj.ipv4_mapped)

    # RFC 6052 Well-Known Prefix for NAT64 (64:ff9b::/96) used in DNS64/dual-stack ISP environments
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in ipaddress.IPv6Network("64:ff9b::/96"):
        embedded_v4 = ipaddress.IPv4Address(ip_obj.packed[-4:])
        return is_ip_blocked(embedded_v4)

    if ip_obj.is_loopback:
        return True
    if ip_obj.is_private:
        return True
    if ip_obj.is_link_local:
        return True
    if ip_obj.is_multicast:
        return True
    if ip_obj.is_reserved:
        return True

    # Cloud metadata IPv4
    if str(ip_obj) == "169.254.169.254":
        return True

    return False


def validate_safe_url(
    url: str,
    allowed_hosts: Optional[Set[str]] = None,
    allow_private_in_dev: bool = False,
) -> str:
    """
    Validates that a URL is safe from SSRF attacks, protocol smuggling,
    private network probing, and cloud metadata theft.

    Args:
        url: The URL string to validate.
        allowed_hosts: Optional set of allowed domain hostnames.
        allow_private_in_dev: If True, bypasses private IP check for local mocks.

    Returns:
        The validated clean URL string.

    Raises:
        SSRFValidationError: If the URL fails any security check.
    """
    if not url or not isinstance(url, str):
        raise SSRFValidationError("URL cannot be empty", 400)

    clean_url = url.strip()

    try:
        parsed = urlparse(clean_url)
    except Exception as e:
        raise SSRFValidationError(f"Malformed URL: {e}", 400)

    # 1. Scheme validation: only HTTP and HTTPS
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SSRFValidationError(
            f"Unsupported URL scheme '{scheme}'. Only 'http' and 'https' are allowed.",
            400
        )

    # 2. Hostname extraction
    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise SSRFValidationError("URL must include a valid host", 400)

    # 3. Block known metadata hostnames directly
    if hostname in BLOCKED_METADATA_HOSTS:
        raise SSRFValidationError(
            f"Access to metadata host '{hostname}' is blocked for security.",
            403
        )

    # 4. Allowed hosts whitelist check (if specified)
    if allowed_hosts is not None:
        if hostname not in allowed_hosts:
            raise SSRFValidationError(
                f"Host '{hostname}' is not in the allowed hosts list: {', '.join(sorted(allowed_hosts))}",
                403
            )

    # 5. IP Address and DNS Resolution check
    if not allow_private_in_dev:
        # Check if hostname is already a direct IP literal
        try:
            direct_ip = ipaddress.ip_address(hostname)
            if is_ip_blocked(direct_ip):
                raise SSRFValidationError(
                    f"Direct access to private, loopback, or metadata IP '{hostname}' is forbidden.",
                    403
                )
        except ValueError:
            # Not an IP literal; resolve via DNS
            try:
                addr_infos = socket.getaddrinfo(hostname, parsed.port or (443 if scheme == "https" else 80), proto=socket.IPPROTO_TCP)
                for family, socktype, proto, canonname, sockaddr in addr_infos:
                    ip_str = sockaddr[0]
                    resolved_ip = ipaddress.ip_address(ip_str)
                    if is_ip_blocked(resolved_ip):
                        raise SSRFValidationError(
                            f"Host '{hostname}' resolves to blocked private or loopback IP '{ip_str}'.",
                            403
                        )
            except socket.gaierror as dns_err:
                # DNS failure: reject as unreachable host
                logger.debug(f"DNS resolution failed for {hostname}: {dns_err}")
                raise SSRFValidationError(f"Could not resolve host '{hostname}': {dns_err}", 400)

    return clean_url


async def safe_redirect_hook(response: "httpx.Response") -> None:
    """
    HTTPX event hook that intercepts 3xx redirect responses and validates
    that the redirect destination URL does not point to blocked or private addresses.
    """
    if response.is_redirect and "location" in response.headers:
        redirect_url = response.headers["location"]
        # If relative redirect, resolve against current request URL
        from urllib.parse import urljoin
        full_redirect = urljoin(str(response.url), redirect_url)
        # Validate that redirect target is safe
        validate_safe_url(full_redirect, allowed_hosts=GITHUB_ALLOWED_HOSTS)


def create_safe_async_client(
    timeout: float = 30.0,
    allowed_hosts: Optional[Set[str]] = None,
    **kwargs
) -> "httpx.AsyncClient":
    """
    Factory creating an httpx.AsyncClient with SSRF redirect validation hook.
    """
    import httpx

    async def hook(response: httpx.Response):
        if response.is_redirect and "location" in response.headers:
            from urllib.parse import urljoin
            full_redirect = urljoin(str(response.url), response.headers["location"])
            validate_safe_url(full_redirect, allowed_hosts=allowed_hosts or GITHUB_ALLOWED_HOSTS)

    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        event_hooks={"response": [hook]},
        **kwargs
    )
