"""The strict-egress FDP HTTP client.

A single ``httpx.AsyncClient`` pinned to the target FDP's origin (ADR-0018 §3):
every request — including redirect hops — is checked against the allowed origin
and rejected otherwise, so the bridge can never be steered to fetch an arbitrary
IRI. Every call carries a timeout and a response-size cap; oversized bodies are
aborted mid-stream rather than buffered.

This is the shared transport for the whole ``fdp`` client layer (LDP here;
SPARQL/search/shapes in task 1.3). It returns raw ``FetchedDocument``s; parsing
into RDF and shaping into tool results happen above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Self

import httpx
from pydantic import SecretStr

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.errors import (
    EgressError,
    FdpResponseTooLargeError,
    FdpTimeoutError,
    FdpUpstreamError,
)
from fdp_mcp.fdp.links import LinkSet

if TYPE_CHECKING:
    from fdp_mcp.fdp.ldp import LdpResource, RootDiscovery

# A content-negotiation preference an FDP can satisfy: Turtle first (the FDP
# default and most compact), then JSON-LD, then RDF/XML and N-Triples.
DEFAULT_RDF_ACCEPT = (
    "text/turtle;q=1.0, application/ld+json;q=0.9, "
    "application/rdf+xml;q=0.8, application/n-triples;q=0.7"
)


def _origin(url: httpx.URL) -> tuple[str, str, int]:
    """The (scheme, host, port) origin of ``url``, with default ports applied."""
    default_port = 443 if url.scheme == "https" else 80
    return (url.scheme, url.host, url.port or default_port)


@dataclass(frozen=True)
class FetchedDocument:
    """A raw FDP response body plus the bits the layers above it need."""

    url: str
    status: int
    media_type: str
    text: str
    links: LinkSet
    headers: httpx.Headers


class FdpClient:
    """Egress-guarded, size-capped async HTTP client for one target FDP."""

    def __init__(self, settings: FdpMcpSettings, *, credential: SecretStr | None = None) -> None:
        self._settings = settings
        self._base_url = httpx.URL(str(settings.fdp_base_url))
        self._allowed_origin = _origin(self._base_url)
        self._max_bytes = settings.fdp_max_response_bytes
        headers = {"user-agent": "fdp-mcp"}
        if credential is not None:
            # The client's forwarded FDP credential, sent verbatim on this
            # session's requests only. The egress guard ensures it goes solely to
            # the FDP origin; structlog redaction keeps it out of logs.
            headers["authorization"] = f"Bearer {credential.get_secret_value()}"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.fdp_timeout_seconds),
            follow_redirects=True,
            # Redirect hops re-enter this hook, so an off-origin redirect is
            # rejected just like a direct off-origin request.
            event_hooks={"request": [self._guard_egress]},
            headers=headers,
        )
        # Per-session memo of the FDP root record (public metadata reused by
        # discovery + endpoint resolution, ADR-0018 G-05); populated by
        # ``fdp.ldp.fetch_root`` so the root is fetched at most once per session.
        self.root_resource: LdpResource | None = None
        # Per-session memo of root discovery (root + kinds). fdp_info, get_schema,
        # and list_data_services all need it; caching avoids re-crawling the
        # containment tree on every tool call within a session.
        self.root_discovery: RootDiscovery | None = None

    @property
    def base_url(self) -> str:
        """The configured target FDP base URL."""
        return str(self._base_url)

    async def _guard_egress(self, request: httpx.Request) -> None:
        if _origin(request.url) != self._allowed_origin:
            raise EgressError(
                f"refusing request to {request.url} outside FDP origin {self._settings.fdp_origin}"
            )

    def _check_egress(self, url: httpx.URL) -> None:
        if _origin(url) != self._allowed_origin:
            raise EgressError(
                f"refusing request to {url} outside FDP origin {self._settings.fdp_origin}"
            )

    async def get(self, url: str, *, accept: str = DEFAULT_RDF_ACCEPT) -> FetchedDocument:
        """GET ``url`` with the given ``Accept``, enforcing egress + size cap."""
        return await self._fetch("GET", url, headers={"accept": accept})

    async def post(
        self, url: str, *, content: str | bytes, content_type: str, accept: str
    ) -> FetchedDocument:
        """POST a body to ``url`` (e.g. a SPARQL query, a search JSON), guarded."""
        return await self._fetch(
            "POST",
            url,
            headers={"accept": accept, "content-type": content_type},
            content=content,
        )

    async def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: str | bytes | None = None,
    ) -> FetchedDocument:
        """Send one request, enforcing egress + size cap.

        Raises ``EgressError`` (off-origin), ``FdpTimeoutError`` (timeout),
        ``FdpResponseTooLargeError`` (over cap), or ``FdpUpstreamError``
        (transport failure). HTTP status is returned in the document; status →
        error mapping is the caller's job (``errors.raise_for_status``).
        """
        target = httpx.URL(url)
        # Explicit pre-check for a clear, early error on the initial URL; the
        # event hook is the backstop for redirect hops.
        self._check_egress(target)
        try:
            async with self._client.stream(
                method, target, headers=headers, content=content
            ) as response:
                declared = response.headers.get("content-length")
                if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
                    raise FdpResponseTooLargeError(
                        f"{declared} bytes declared, cap is {self._max_bytes}"
                    )
                body = await self._read_capped(response)
                media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                text = body.decode(response.encoding or "utf-8", errors="replace")
                return FetchedDocument(
                    url=str(response.url),
                    status=response.status_code,
                    media_type=media_type,
                    text=text,
                    links=LinkSet.from_header(response.headers.get("link")),
                    headers=response.headers,
                )
        except httpx.TimeoutException as exc:
            raise FdpTimeoutError(str(target)) from exc
        except httpx.TransportError as exc:  # connection/DNS/protocol failures
            raise FdpUpstreamError(f"transport error for {target}: {exc}") from exc

    async def _read_capped(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise FdpResponseTooLargeError(f"response exceeded cap of {self._max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
