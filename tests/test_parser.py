"""Unit tests for Groww scheme page parser."""

import json
from pathlib import Path

import pytest

from ingestion.parser import (
    ParsedSchemePage,
    parse_html,
    parse_raw_html_file,
    write_parsed_outputs,
)

FIXTURE_HTML = """
<html>
  <head><title>HDFC Mid Cap Fund Direct Growth - NAV</title></head>
  <body>
    <nav>Home Stocks Mutual Funds</nav>
    <footer>Contact Us GROWW All rights reserved</footer>
    <h1>HDFC Mid Cap Fund Direct Growth</h1>
    <div>
      <span>Equity</span><span>Mid Cap</span><span>Very High Risk</span>
      <span class="contentSecondary bodyBase">Fund size (AUM)</span>
      <span class="bodyLargeHeavy">₹97,350.48 Cr</span>
      <span class="contentSecondary bodyBase">Expense ratio</span>
      <span class="bodyLargeHeavy">0.75%</span>
      <span class="contentSecondary bodyBase">Min. for SIP</span>
      <span class="bodyLargeHeavy">₹100</span>
    </div>
    <h2>Minimum investments</h2>
    <div>Min. for 1st investment ₹100 Min. for SIP ₹100</div>
    <h2>Return calculator</h2>
    <div>Should be removed</div>
    <h4>Exit load, stamp duty and tax</h4>
    <div class="exitLoadStampDutyTax_contentContainer">
      <h4>Exit load</h4>
      <p>Exit load of 1% if redeemed within 1 year.</p>
      <h4>Tax implication</h4>
      <p>If you redeem within one year, returns are taxed at 20%.</p>
    </div>
    <h4>Investment Objective</h4>
    <div>The scheme seeks long-term capital appreciation in Mid-Cap companies.</div>
    <div class="investmentObjective_benchmarkRow">
      <span class="contentSecondary bodyBase">Fund benchmark</span>
      <span class="bodyLargeHeavy">NIFTY Midcap 150 Total Return Index</span>
    </div>
    <h2>Holdings (78)</h2>
    <table>
      <tr><th>Name</th><th>Sector</th><th>Instruments</th><th>Assets</th></tr>
      <tr><td>Repo</td><td>Unspecified</td><td>Repo</td><td>7.68%</td></tr>
    </table>
    <h2>Returns and rankings</h2>
    <table>
      <tr><th>Name</th><th>3Y</th><th>5Y</th></tr>
      <tr><td>Fund returns</td><td>+21.0%</td><td>+20.7%</td></tr>
    </table>
    <div class="compareSimilarFunds_container">Compare similar funds noise</div>
  </body>
</html>
"""


def test_parse_html_extracts_fund_name_category_and_key_fields() -> None:
    parsed = parse_html(
        FIXTURE_HTML,
        scheme_name="HDFC Mid Cap Fund Direct Growth",
        scheme_category="Equity — Mid Cap",
    )

    assert parsed.fund_name == "HDFC Mid Cap Fund Direct Growth"
    assert parsed.category == "Equity — Mid Cap"
    assert parsed.label_values["Expense ratio"] == "0.75%"
    assert parsed.label_values["Min. for SIP"] == "₹100"
    assert parsed.label_values["Fund benchmark"] == "NIFTY Midcap 150 Total Return Index"
    assert "Minimum investments" in parsed.sections
    assert "Exit load of 1% if redeemed within 1 year." in parsed.text
    assert "Return calculator" not in parsed.text
    assert "Compare similar funds" not in parsed.text


def test_parse_html_extracts_returns_table_and_skips_holdings() -> None:
    parsed = parse_html(FIXTURE_HTML)

    table_titles = [table.title for table in parsed.tables]
    assert "Returns and rankings" in table_titles
    assert not any(title and title.startswith("Holdings") for title in table_titles)


def test_write_parsed_outputs_creates_txt_and_json_files(tmp_path: Path) -> None:
    parsed = ParsedSchemePage(
        fund_name="HDFC Mid Cap Fund Direct Growth",
        category="Equity — Mid Cap",
        sections={"Minimum investments": "Min. for SIP ₹100"},
        label_values={"Expense ratio": "0.75%"},
        text="Expense ratio: 0.75%",
    )

    outputs = write_parsed_outputs(
        parsed,
        slug="hdfc-mid-cap-fund-direct-growth",
        source_url="https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        processed_dir=tmp_path,
    )

    assert outputs["txt"].name == "hdfc-mid-cap-fund-direct-growth.txt"
    assert outputs["json"].name == "hdfc-mid-cap-fund-direct-growth.json"
    assert "Fund: HDFC Mid Cap Fund Direct Growth" in outputs["txt"].read_text(encoding="utf-8")

    payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert payload["fund_name"] == "HDFC Mid Cap Fund Direct Growth"
    assert payload["label_values"]["Expense ratio"] == "0.75%"
    assert payload["sections"]["Minimum investments"] == "Min. for SIP ₹100"


def test_parse_raw_html_file_uses_real_snapshot_if_present() -> None:
    raw_path = Path("data/raw/hdfc-mid-cap-fund-direct-growth.html")
    if not raw_path.is_file():
        pytest.skip("Raw Groww HTML snapshot not available")

    parsed = parse_raw_html_file(
        raw_path,
        scheme_name="HDFC Mid Cap Fund Direct Growth",
        scheme_category="Equity — Mid Cap",
    )

    assert parsed.fund_name == "HDFC Mid Cap Fund Direct Growth"
    assert parsed.label_values.get("Expense ratio") == "0.75%"
    assert "Exit load of 1% if redeemed within 1 year." in parsed.text
    assert "NIFTY Midcap 150 Total Return Index" in parsed.text
    assert "All rights reserved" not in parsed.text
