# ticker-explain

Code commit: d303e491ae28be51c052a883d2a329bae7ece8b3

Checked head: 43cfbc7cde448c55c5fd0866c63d8e2f1dc36055

## Build

`white-cliff page --out white-cliff.html`

The command writes one self-contained HTML file. It is not part of `white-cliff site`, and `white-cliff.html` is gitignored, so the built file is not committed. From a checkout, before install:

`PYTHONPATH=src python3 -m white_cliff page --out white-cliff.html`

## Tests

257 passed.

## CI

All four checks on 43cfbc7cde448c55c5fd0866c63d8e2f1dc36055 succeeded.

Push run 44307380679: authorship 134812344540, test 134812344098.

Pull request run 44307764276: authorship 134813653773, test 134813653207.

## Authorship

Checked `git log --format='%an|%ae|%cn|%ce|%(trailers:only)' 6397b468a59a725d727a9b7abf5b3756655fa76f..HEAD` before the push. Every commit after the root is Erik Eicke as author and committer, with an empty trailer. The address is the one in git config and is not copied here.

## What the page does

The disclaimer is the first text. The next line is the saved-copies line. Provenance has two save dates, so the line names both: 9 filings, November 17, 2026 and November 18, 2026. Picking one date would have been false.

A company name or ticker matches in Python (`normalize`, `match_query`). The page embeds those keys. The script uses the same suffix list, generated from `SUFFIXES`. CI installs Python only, so the script is not run there. The tests check the Python matcher and that the embedded keys equal `companies_for`.

No match shows one sentence and leaves the company buttons. A query that fits two companies matches nothing.

The button opens that company's latest saved 10-K or 10-Q. Every pinned filing that has figures is still a section on the page. The Apple 8-K has no figures, so it is counted in the 9 and has no section.

Each figure uses the same sec.gov URL as `white-cliff explain`. The advice guard runs on the page text after the disclaimer, the script, and the style are removed.

No `explain <TICKER>` command was added. That work had not been written.

## Saved companies

Names and tickers are the filing's own `dei:EntityRegistrantName` and `dei:TradingSymbol` values. Extra symbols are on the cover, so they match too. They are not guessed.

| Company | Shown filing | Tickers on the cover |
| --- | --- | --- |
| Alphabet Inc. | 0001652044-26-000084 | GOOG, GOOGL, GOOGM, GOOGN |
| Apple Inc. | 0000320193-26-000026 | AAPL |
| COCA COLA CO | 0001628280-26-010047 | KO, KO26, KO26C, KO27, KO29A, KO29B, KO30B, KO31, KO32, KO33, KO33A, KO35, KO36, KO36A, KO37, KO40B, KO41, KO44, KO53 |
| Exxon Mobil Corporation | 0000034088-26-000045 | XOM, XOM28, XOM32, XOM39A |
| Johnson & Johnson | 0000200406-26-000016 | JNJ, JNJ28, JNJ29B, JNJ32, JNJ33B, JNJ35, JNJ36A, JNJ37B, JNJ44, JNJ45, JNJ55 |
| MICROSOFT CORPORATION | 0001193125-26-436133 | MSFT |
| Walmart Inc. | 0000104169-26-000055 | WMT, WMT26, WMT26A, WMT28C, WMT29B, WMT30B, WMT31A, WMT34, WMT35A, WMT39 |

Apple's quarterly report 0000320193-26-000020 is a section. The Apple button opens the later annual report.

## Where it is tested

| Item | Code | Test |
| --- | --- | --- |
| Build command | `src/white_cliff/cli.py:49` and `:129` | `test_saved_line_uses_the_provenance_count_and_dates` |
| Disclaimer, box, Explain, buttons | `src/white_cliff/page.py:491` | `test_saved_line_uses_the_provenance_count_and_dates`, `test_page_lists_every_saved_filing_that_has_figures` |
| Saved count and dates | `src/white_cliff/page.py:183` | `test_saved_line_uses_the_provenance_count_and_dates` |
| Cover name and ticker, or a refusal | `src/white_cliff/page.py:112` | `test_cover_comes_from_the_filing_and_refuses_a_gap`, `test_a_missing_cover_writes_nothing` |
| Forgiving match, no guess | `src/white_cliff/page.py:92` and `:101` | `test_matching_is_forgiving_and_does_not_guess` |
| Latest 10-K or 10-Q, embedded keys | `src/white_cliff/page.py:239` and `:270` | `test_page_lists_every_saved_filing_that_has_figures`, `test_embedded_keys_agree_with_the_python_matcher` |
| Figures and sec.gov links | `src/white_cliff/page.py:274` and `:298` | `test_figures_match_the_explain_output_and_expected_json` |
| No network, large type | `src/white_cliff/page.py:322` and `:392` | `test_page_makes_no_network_request` |
| Advice guard | `src/white_cliff/page.py:509` | `test_page_text_passes_the_advice_guard` |
