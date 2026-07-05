"""Unit tests for Groww scheme page fetcher."""

from pathlib import Path

import httpx
import pytest
import yaml

from ingestion.fetcher import (
    FetchError,
    SchemeSource,
    fetch_all_schemes,
    fetch_scheme_page,
    load_sources,
    url_to_slug,
)


def test_url_to_slug_extracts_final_path_segment() -> None:
    url = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
    assert url_to_slug(url) == "hdfc-mid-cap-fund-direct-growth"


def test_load_sources_reads_all_five_schemes(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text(
        yaml.dump(
            {
                "amc": "HDFC Mutual Fund",
                "schemes": [
                    {
                        "name": "HDFC Large Cap Fund Direct Growth",
                        "category": "Equity — Large Cap",
                        "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
                        "aliases": ["large cap"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    schemes = load_sources(config)
    assert len(schemes) == 1
    assert schemes[0].name == "HDFC Large Cap Fund Direct Growth"
    assert schemes[0].aliases == ("large cap",)


def test_fetch_scheme_page_saves_html(tmp_path: Path) -> None:
    scheme = SchemeSource(
        name="HDFC Mid Cap Fund Direct Growth",
        category="Equity — Mid Cap",
        url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        aliases=("mid cap",),
    )
    html = "<html><body>" + ("fund facts " * 200) + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, request=request)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    result = fetch_scheme_page(scheme, raw_dir=tmp_path, client=client)

    assert result.from_cache is False
    assert result.output_path == tmp_path / "hdfc-mid-cap-fund-direct-growth.html"
    assert result.output_path.read_text(encoding="utf-8") == html
    client.close()


def test_fetch_scheme_page_uses_cache_after_retries(tmp_path: Path) -> None:
    scheme = SchemeSource(
        name="HDFC Mid Cap Fund Direct Growth",
        category="Equity — Mid Cap",
        url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        aliases=("mid cap",),
    )
    cached_html = "<html><body>" + ("cached snapshot " * 200) + "</body></html>"
    output_path = tmp_path / "hdfc-mid-cap-fund-direct-growth.html"
    output_path.write_text(cached_html, encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Unavailable", request=request)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    result = fetch_scheme_page(
        scheme,
        raw_dir=tmp_path,
        client=client,
        use_cache_on_failure=True,
    )

    assert result.from_cache is True
    assert result.output_path.read_text(encoding="utf-8") == cached_html
    client.close()


def test_fetch_scheme_page_raises_on_404(tmp_path: Path) -> None:
    scheme = SchemeSource(
        name="Missing Scheme",
        category="Equity — Large Cap",
        url="https://groww.in/mutual-funds/does-not-exist",
        aliases=(),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found", request=request)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    with pytest.raises(FetchError) as exc_info:
        fetch_scheme_page(scheme, raw_dir=tmp_path, client=client)

    assert exc_info.value.failed_urls == [scheme.url]
    client.close()


def test_fetch_all_schemes_reports_failed_urls(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text(
        yaml.dump(
            {
                "amc": "HDFC Mutual Fund",
                "schemes": [
                    {
                        "name": "Scheme A",
                        "category": "Equity — Large Cap",
                        "url": "https://groww.in/mutual-funds/scheme-a",
                        "aliases": [],
                    },
                    {
                        "name": "Scheme B",
                        "category": "Equity — Mid Cap",
                        "url": "https://groww.in/mutual-funds/scheme-b",
                        "aliases": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("scheme-a"):
            html = "<html><body>" + ("ok " * 400) + "</body></html>"
            return httpx.Response(200, text=html, request=request)
        return httpx.Response(404, text="Not Found", request=request)

    monkeypatch.setattr("ingestion.fetcher.time.sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(FetchError) as exc_info:
        fetch_all_schemes(
            config_path=config,
            raw_dir=tmp_path,
            client=client,
            use_cache_on_failure=False,
        )
    client.close()

    assert exc_info.value.failed_urls == ["https://groww.in/mutual-funds/scheme-b"]
    assert (tmp_path / "scheme-a.html").is_file()
