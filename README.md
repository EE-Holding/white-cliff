This tool explains the numbers in a public company filing. It does not recommend buying, selling or holding any security, and it is not investment advice.

# white-cliff

white-cliff explains a public company filing in plain language. It reads a US EDGAR annual report, quarterly report, or earnings exhibit and shows revenue, margins, cash flow, debt, and share count. Every figure points back to the filing. The tool does not recommend buying, selling, or holding any security.

Figures come from EDGAR. The tool does not use prices, estimates, news, or any other source. It does not compute price multiples. Explanations use fixed sentences.

## Install

```bash
pip install -e ".[dev]"
```

Set a User-Agent that includes your name and a contact email before any command other than help. The package does not include a contact address or a key.

```bash
export WHITE_CLIFF_USER_AGENT="Example Name name@example.com"
```

You can also put `user_agent = "Example Name name@example.com"` in the config file named by `WHITE_CLIFF_CONFIG`.

## Commands

Explain an accession number, or a local filing directory that contains `provenance.json` and the raw file:

```bash
white-cliff explain 0000320193-26-000026
white-cliff explain pinned/filings/0000320193-26-000026
white-cliff explain pinned/filings/0000320193-26-000026 --format html --output explanation.html
white-cliff explain pinned/filings/0000320193-26-000026 --copy
```

Write static HTML for the pinned filings. Publish the `docs` directory with GitHub Pages. No separate host is required.

```bash
white-cliff site --output docs
```

Requests to EDGAR send the User-Agent you configured. The client stays at or under ten requests per second, backs off on HTTP 403 and 429, and refuses any host other than the EDGAR hosts. It fetches only the filing you asked for.

## What the output guarantees

The disclaimer above is the first paragraph of every explanation, of this file, of `--help`, and of every export. An output that lacks it is refused.

Every shown number comes from the fact store or from a named formula in the formula library. The library records the formula and the input identifiers, and it refuses mismatched units, mismatched periods, and any price input. A section that fails a check is omitted with a reason.

Confidential omissions such as `[***]` are shown as filed. Spans shaped like a social security number, a bank or account number, or a home address are replaced by a source chip.

Quotes, when present, are at most one sentence and 50 words, at most three per section, and each links to the filing on sec.gov.

## Report an error

If a number, source, or omission looks wrong, open a filing error report:

https://github.com/EE-Holding/white-cliff/issues/new?template=filing_error.md

A confirmed misstatement is corrected or the output pulled within 2 business days, with a dated correction note. The log is [CORRECTIONS.md](CORRECTIONS.md).

## Pinned filings

The `pinned` directory holds real EDGAR filings, the SHA-256 of each raw file, and hand-checked expected facts. The manifest is a list, so the set can grow to 30 filings. The current set covers technology, retail, consumer staples, energy, and health care, including an annual report, a quarterly report, and an earnings exhibit.

## License

Copyright 2026 Erik Eicke

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.
