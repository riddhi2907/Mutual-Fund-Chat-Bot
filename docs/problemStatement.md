# Problem Statement: Mutual Fund FAQ Assistant (Facts-Only Q&A)

## Overview

The objective of this project is to build a **facts-only FAQ assistant** for mutual fund schemes, using **Groww** as the reference product context. The assistant will answer objective, verifiable queries related to mutual funds by retrieving information exclusively from official public sources, such as AMC (Asset Management Company) websites, AMFI, and SEBI.

The system must strictly avoid providing investment advice, opinions, or recommendations. Every response must include a single, clear source link and adhere to defined constraints around clarity, accuracy, and compliance.

## Objective

Design and implement a lightweight **Retrieval-Augmented Generation (RAG)**-based assistant that:

- Answers factual queries about mutual fund schemes
- Uses a curated corpus of official documents
- Provides concise, source-backed responses

## Target Users

- Retail investors comparing mutual fund schemes
- Customer support and content teams handling repetitive mutual fund queries

## Selected AMC & Schemes

This RAG chatbot is scoped to **HDFC Mutual Fund** (HDFC AMC), with **five schemes** spanning equity and commodity categories. [Groww](https://groww.in) fund pages are used as the **reference product context** for UX and example queries; the RAG corpus must still be built from **official public sources** (HDFC AMC, AMFI, SEBI).

| # | Scheme | Category | Risk | Groww Reference |
|---|--------|----------|------|-----------------|
| 1 | HDFC Large Cap Fund Direct Growth | Equity — Large Cap | Very High | [View on Groww](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth) |
| 2 | HDFC Mid Cap Fund Direct Growth | Equity — Mid Cap | Very High | [View on Groww](https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth) |
| 3 | HDFC Small Cap Fund Direct Growth | Equity — Small Cap | Very High | [View on Groww](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth) |
| 4 | HDFC Gold ETF Fund of Fund Direct Plan Growth | Commodities — Gold | High | [View on Groww](https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth) |
| 5 | HDFC Silver ETF FoF Direct Growth | Commodities — Silver | Very High | [View on Groww](https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth) |

**Category diversity covered:** large-cap, mid-cap, small-cap equity, and gold/silver commodity FoF schemes.

**AMC details:** [HDFC Mutual Fund](http://www.hdfcfund.com) — Registrar: CAMS.

## Scope of Work

### 1. Corpus Definition

- **AMC:** HDFC Mutual Fund (HDFC AMC)
- **Schemes:** The five HDFC schemes listed above
- **Corpus size:** 5 scheme reference pages (below) plus official AMC, AMFI, and SEBI documents linked from or associated with these schemes

#### Scheme reference pages (Groww)

These URLs define the scope of the RAG chatbot and serve as the primary scheme-level corpus entry points:

| Scheme | URL |
|--------|-----|
| HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| HDFC Small Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| HDFC Gold ETF Fund of Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth |
| HDFC Silver ETF FoF Direct Growth | https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth |

#### Supplemental official sources

Ingest factual content from official public documents for the schemes above, including:

| Source type | URL / location |
|-------------|----------------|
| AMC website | http://www.hdfcfund.com |
| Scheme factsheets | HDFC AMC — per-scheme factsheet pages/PDFs |
| KIM (Key Information Memorandum) | HDFC AMC — per-scheme KIM documents |
| SID (Scheme Information Document) | HDFC AMC — per-scheme SID documents (linked from Groww scheme pages) |
| AMC FAQ / help pages | HDFC AMC investor services & FAQs |
| AMFI guidance | https://www.amfiindia.com |
| SEBI guidance | https://www.sebi.gov.in (mutual funds / investor education) |
| Statement & tax document guides | HDFC AMC / CAMS investor portal documentation |

**Ingestion note:** Groww pages are used as scheme reference and navigation context; verifiable facts in responses must cite the underlying official document (factsheet, KIM, SID, AMFI, or SEBI source), not the Groww page itself.

### 2. FAQ Assistant Requirements

The assistant must:

**Answer facts-only queries**, such as:

- Expense ratio of a scheme (e.g., HDFC Mid Cap Fund Direct Growth)
- Exit load details (e.g., HDFC Gold ETF FoF redemption within 15 days)
- Minimum SIP amount (e.g., ₹100 for HDFC Large Cap Fund Direct Growth)
- Riskometer classification (e.g., Very High for HDFC Small Cap Fund Direct Growth)
- Benchmark index (e.g., NIFTY 100 Total Return Index for HDFC Large Cap; Domestic Price of Gold for HDFC Gold ETF FoF)
- Process to download statements or capital gains reports

**Ensure:**

- Each response is limited to a maximum of **3 sentences**
- Each response includes **exactly one citation link**
- Each response includes a footer:
  > Last updated from sources: \<date\>

### 3. Refusal Handling

The assistant must refuse non-factual or advisory queries, such as:

- "Should I invest in this fund?"
- "Which fund is better?"

Refusal responses should:

- Be polite and clearly worded
- Reinforce the facts-only limitation
- Provide a relevant educational link (e.g., AMFI or SEBI resource)

### 4. User Interface (Minimal)

The solution should include a simple interface with:

- A welcome message scoped to HDFC Mutual Fund schemes
- Three example questions, such as:
  - "What is the expense ratio of HDFC Mid Cap Fund Direct Growth?"
  - "What is the exit load on HDFC Gold ETF Fund of Fund?"
  - "What is the benchmark for HDFC Large Cap Fund Direct Growth?"
- A visible disclaimer:
  > Facts-only. No investment advice.

## Constraints

### Data and Sources

- Use only official public sources (AMC, AMFI, SEBI)
- Do not use third-party blogs or aggregator websites

### Privacy and Security

Do not collect, store, or process:

- PAN or Aadhaar numbers
- Account numbers
- OTPs
- Email addresses or phone numbers

### Content Restrictions

- No investment advice or recommendations
- No performance comparisons or return calculations
- For performance-related queries, provide a link to the official factsheet only

### Transparency

- Responses must be short, factual, and verifiable
- Every answer must include a source link and last updated date

## Expected Deliverables

### README Document

- Setup instructions
- Selected AMC (**HDFC Mutual Fund**) and the five schemes listed above
- Architecture overview (RAG approach)
- Known limitations

### Disclaimer Snippet

> Facts-only. No investment advice.

## Success Criteria

- Accurate retrieval of factual mutual fund information
- Strict adherence to facts-only responses
- Consistent inclusion of valid source citations
- Proper refusal of advisory queries
- Clean, minimal, and user-friendly interface

## Summary

The goal is to build a trustworthy, transparent, and compliant mutual fund FAQ assistant for **HDFC Mutual Fund** schemes that prioritizes **accuracy over intelligence**. The system should ensure that users receive only verified, source-backed financial information about the five selected funds — across large-cap, mid-cap, small-cap, and gold/silver commodity categories — without any advisory bias or speculative content.
