"""Header handling when following redirects to partner APIs.

Contract: when a redirect crosses to a DIFFERENT host, credential
headers from the original request (Authorization, Cookie,
Proxy-Authorization) must be stripped before the request is
re-sent — the receiving host is a different trust domain and must
never see the caller's credentials.  Same-host redirects keep all
headers, including credentials, because the trust domain has not
changed.  The comparison is on the URL hostname only: a change of
scheme or port on the same host is still the same host, while a
subdomain of the original host is a different host and receives
no credential headers.  The caller's header mapping is never
mutated; a new dict is returned in every case.
"""

from urllib.parse import urlparse

SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"})


def headers_for_redirect(headers, original_url, redirect_url):
    """Return the headers safe to send to ``redirect_url``."""
    original_host = urlparse(original_url).hostname
    redirect_host = urlparse(redirect_url).hostname
    if redirect_host == original_host:
        return dict(headers)
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in SENSITIVE_HEADERS
    }
