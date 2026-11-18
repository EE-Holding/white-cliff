# compare

Code commit: 725620c34ebe192828e1766a50a3c880505aaa39

## Tests

339 passed.

New cases:

- `test_pinned_nvidia_share_count_check_runs`
- `test_a_missing_current_diluted_count_and_a_zero_basic_count_name_themselves`
- `test_a_prior_quarter_from_before_a_fiscal_year_change_is_not_used`
- `test_a_column_the_form_cannot_carry_uses_the_filing_sentence`
- `test_a_zero_change_in_diluted_shares_does_not_say_rose`
- `test_a_zero_earlier_cost_does_not_use_the_inventory_reason`
- `test_the_disclaimer_comes_before_the_framing_line_and_there_is_no_heading`
- `test_banned_words_are_refused_on_a_rendered_page_and_the_required_lines_are_allowed`
- `test_an_in_line_check_lists_only_items_at_or_above_the_threshold`

## What the page shows

Each figure is compared with last quarter and with the same period a year earlier. A per-share figure says "per share".

The share-count check runs on the pinned NVIDIA quarterly report. A missing current diluted count says "Diluted shares is not in the filing." A basic count of zero or less says "The basic share count is zero or less."

A prior quarterly report from before a fiscal-year change is not used as last quarter. Each candidate carries its own fiscal year end.

Template M6, for a column the form cannot carry: "{figure} for the prior quarter is not available for this filing." That line is used for a 10-K's last quarter, a first quarter's prior quarter, and operating cash flow's last quarter in a second or third quarter. Those columns do not use the "not in the filings White Cliff read" line, and nothing is derived to fill them. A second-quarter revenue figure with no prior report still uses that missing-filing line.

A change of exactly 0.0 says "was unchanged", from the unchanged sentence "{figure} was unchanged from {period_prev} at {value}."

When the earlier cost of sales is zero or less, the inventory check says "The earlier cost of sales figure is zero or less."

The checks have no heading. The page order is the opening line first, then "These checks compare the company's own reported numbers with each other. They are not a judgement of the company and not investment advice."

Banned words are checked on every rendered page. Those two lines are allowed.

An in-line items check lists only items at or above 10 percent of operating income.

The NVIDIA lookup shows the NVIDIA filing, including $96,221 million. Screenshot of the NVIDIA result.

## Not done

The first concept present in both periods is not yet preferred over a not-available line. The year-over-year scan still stops at the first mismatch.

## CI

Local suite passed. The branch push is the CI run for this commit.

## Authorship

Author and committer are Erik Eicke, with an empty trailer.
