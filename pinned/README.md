This tool explains the numbers in a public company filing. It does not recommend buying, selling or holding any security, and it is not investment advice.

# Pinned filings

Each accession is a directory under `filings/`. The directory holds the raw EDGAR files, `provenance.json` (URL, SHA-256, and retrieval time), and `expected.json` (facts read from the primary 10-K or 10-Q).

`sha256` is the raw file. EDGAR appends `<script type="text/javascript" src="..."></script>` immediately before `</body>`, and that src path changes on every download. `content_sha256` is the file with that one trailing script removed and `</body>` left in place. A script anywhere else is kept.

`manifest.json` lists the set. `target_count` is 30. To grow the set, add a directory and append one object to `filings`. Do not invent expected values; each value must appear in the raw file.

Each manifest entry records the filer's SIC code and description from its EDGAR submissions file, with that file's URL. A filing with no SIC has no sector. Forms already present: annual report, quarterly report, and earnings exhibit.
