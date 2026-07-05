"""HTTP fetcher for Groww scheme pages with rate limiting and raw HTML persistence."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "sources.yaml"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
RATE_LIMIT_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {403, 429, 500, 502, 503, 504}
MIN_HTML_BYTES = 1024


@dataclass(frozen=True)
class SchemeSource:
    """A Groww scheme entry from the source registry."""

    name: str
    category: str
    url: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class FetchResult:
    """Outcome of fetching (or reusing) a single scheme page."""

    scheme_name: str
    url: str
    slug: str
    output_path: Path
    fetched_at: datetime
    from_cache: bool
    status_code: int | None


class FetchError(Exception):
    """Raised when one or more scheme pages could not be fetched."""

    def __init__(self, message: str, failed_urls: list[str]) -> None:
        super().__init__(message)
        self.failed_urls = failed_urls


def url_to_slug(url: str) -> str:
    """Derive `{scheme_slug}` from a Groww mutual fund URL path."""
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    if not slug:
        raise ValueError(f"Cannot derive scheme slug from URL: {url}")
    return slug


def load_sources(config_path: Path | None = None) -> list[SchemeSource]:
    """Load scheme definitions from ``config/sources.yaml``."""
    path = config_path or DEFAULT_CONFIG_PATH
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    schemes: list[SchemeSource] = []
    for entry in data.get("schemes", []):
        schemes.append(
            SchemeSource(
                name=entry["name"],
                category=entry["category"],
                url=entry["url"],
                aliases=tuple(entry.get("aliases", [])),
            )
        )
    return schemes


def _validate_html(html: str, url: str) -> None:
    if len(html.encode("utf-8")) < MIN_HTML_BYTES:
        raise ValueError(f"Response body too small for {url}")


def _read_cached_html(output_path: Path) -> str | None:
    if not output_path.is_file():
        return None
    html = output_path.read_text(encoding="utf-8")
    try:
        _validate_html(html, str(output_path))
    except ValueError:
        return None
    return html


def _write_html(output_path: Path, html: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def fetch_scheme_page(
    scheme: SchemeSource,
    *,
    raw_dir: Path | None = None,
    client: httpx.Client | None = None,
    use_cache_on_failure: bool = True,
) -> FetchResult:
    """
    Fetch one Groww scheme page and save raw HTML to ``data/raw/{scheme_slug}.html``.

    On transient HTTP failures, retries with exponential backoff. If all retries
    fail and ``use_cache_on_failure`` is True, falls back to an existing snapshot.
    """
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    slug = url_to_slug(scheme.url)
    output_path = raw_dir / f"{slug}.html"
    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": DEFAULT_USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    )

    last_error: Exception | None = None
    status_code: int | None = None

    try:
        for attempt in range(MAX_RETRIES):
            try:
                response = client.get(scheme.url)
                status_code = response.status_code

                if response.status_code == 404:
                    raise FetchError(
                        f"404 Not Found: {scheme.url}",
                        failed_urls=[scheme.url],
                    )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                response.raise_for_status()
                html = response.text
                _validate_html(html, scheme.url)
                _write_html(output_path, html)

                fetched_at = datetime.now(timezone.utc)
                logger.info("Fetched %s -> %s", scheme.url, output_path.name)
                return FetchResult(
                    scheme_name=scheme.name,
                    url=scheme.url,
                    slug=slug,
                    output_path=output_path,
                    fetched_at=fetched_at,
                    from_cache=False,
                    status_code=status_code,
                )
            except FetchError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    sleep_seconds = RETRY_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Attempt %s/%s failed for %s (%s); retrying in %.1fs",
                        attempt + 1,
                        MAX_RETRIES,
                        scheme.url,
                        exc,
                        sleep_seconds,
                    )
                    time.sleep(sleep_seconds)
    finally:
        if owns_client:
            client.close()

    if use_cache_on_failure:
        cached_html = _read_cached_html(output_path)
        if cached_html is not None:
            logger.warning(
                "Using cached snapshot for %s after fetch failure: %s",
                scheme.url,
                last_error,
            )
            return FetchResult(
                scheme_name=scheme.name,
                url=scheme.url,
                slug=slug,
                output_path=output_path,
                fetched_at=datetime.fromtimestamp(
                    output_path.stat().st_mtime, tz=timezone.utc
                ),
                from_cache=True,
                status_code=status_code,
            )

    raise FetchError(
        f"Failed to fetch {scheme.url}: {last_error}",
        failed_urls=[scheme.url],
    )


def fetch_all_schemes(
    *,
    config_path: Path | None = None,
    raw_dir: Path | None = None,
    client: httpx.Client | None = None,
    use_cache_on_failure: bool = True,
) -> list[FetchResult]:
    """
    Fetch all schemes from the source registry with 1 req/sec rate limiting.

    Raises ``FetchError`` listing every failed URL if any scheme cannot be fetched.
    """
    schemes = load_sources(config_path)
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    results: list[FetchResult] = []
    failed_urls: list[str] = []

    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": DEFAULT_USER_AGENT},
        follow_redirects=True,
        timeout=30.0,
    )

    try:
        for index, scheme in enumerate(schemes):
            if index > 0:
                time.sleep(RATE_LIMIT_SECONDS)
            try:
                result = fetch_scheme_page(
                    scheme,
                    raw_dir=raw_dir,
                    client=client,
                    use_cache_on_failure=use_cache_on_failure,
                )
                results.append(result)
            except FetchError as exc:
                failed_urls.extend(exc.failed_urls)
    finally:
        if owns_client:
            client.close()

    if failed_urls:
        raise FetchError(
            "Fetch failed for the following URLs:\n"
            + "\n".join(f"  - {url}" for url in failed_urls),
            failed_urls=failed_urls,
        )

    return results


def main() -> None:
    """CLI entry point: fetch all Groww scheme pages into ``data/raw/``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    results = fetch_all_schemes()
    cached = sum(1 for result in results if result.from_cache)
    fresh = len(results) - cached
    logger.info(
        "Fetched %s scheme page(s): %s fresh, %s from cache",
        len(results),
        fresh,
        cached,
    )


if __name__ == "__main__":
    main()
