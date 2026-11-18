This tool explains the numbers in a public company filing. It does not recommend buying, selling or holding any security, and it is not investment advice.

# Pinned filings

Each accession is a directory under `filings/`. The directory holds the raw EDGAR file, `provenance.json` (URL, SHA-256, and retrieval time), and `expected.json` (facts read from that file).

`manifest.json` lists the set. `target_count` is 30. To grow the set, add a directory and append one object to `filings`. Do not invent expected values; each value must appear in the raw file.

Each manifest entry records the filer's SIC code and description from its EDGAR submissions file, with that file's URL. A filing with no SIC has no sector. Forms already present: annual report, quarterly report, and earnings exhibit.
