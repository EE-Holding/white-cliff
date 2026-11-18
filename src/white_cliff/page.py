"""One HTML file that explains the saved filings. It does not use the network."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat

from white_cliff.advice import advice_reason
from white_cliff.disclaimer import DISCLAIMER, OutputRefused, ensure_safe_output
from white_cliff.pipeline import explain_filing, load_directory
from white_cliff.sitebuild import pinned_dir
from white_cliff.xbrl import MONEY_ROLES

SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "plc",
        "llc",
        "lp",
    }
)

_NS = "\x1f"
_IX = frozenset(
    {
        "http://www.xbrl.org/2013/inlineXBRL",
        "http://www.xbrl.org/2008/inlineXBRL",
    }
)
_COVER = frozenset({"EntityRegistrantName", "TradingSymbol"})
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_PARAGRAPH = re.compile(r"<p\b[^>]*>.*?</p>", re.S)
_FIGURE = re.compile(
    r'<data data-kind="(?P<kind>fact|calc)" data-id="(?P<id>[^"]+)">(?P<label>[^<]*)</data>\s*'
    r'<a class="source-chip" data-id="(?P=id)" href="(?P<href>[^"]+)">(?P<title>[^<]*)</a>'
)
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S)
_HREF = re.compile(r'href="([^"]*)"')


class CoverError(Exception):
    """The filing does not state one company name and at least one ticker."""


@dataclass(frozen=True)
class Cover:
    name: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class Company:
    name: str
    keys: tuple[str, ...]
    filing: str


@dataclass(frozen=True)
class _Record:
    accession: str
    cik: str
    form: str
    period_end: str
    cover: Cover
    directory: Path
    copied: tuple[str, ...]


def normalize(text: str) -> str:
    """Lower case, drop punctuation, and drop a trailing Inc, Corp, and the like."""
    cleaned = re.sub(r"[^0-9a-z]+", " ", text.casefold())
    parts = [part for part in cleaned.split() if part]
    while len(parts) > 1 and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


def match_query(query: str, companies: tuple[Company, ...] | list[Company]) -> Company | None:
    """One saved company, or nothing when the query is empty or fits more than one."""
    key = normalize(query)
    if not key:
        return None
    found = [company for company in companies if key in company.keys]
    if len(found) != 1:
        return None
    return found[0]


def read_cover(text: str) -> Cover:
    """Company name and tickers from the filing's own cover tags."""
    names: list[str] = []
    symbols: list[str] = []
    frames: list[dict] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        uri, local = name.split(_NS, 1) if _NS in name else ("", name)
        concept = ""
        for key, value in attrs.items():
            if key.split(_NS)[-1] == "name":
                concept = value.split(":")[-1]
                break
        frames.append(
            {
                "local": local,
                "uri": uri,
                "concept": concept,
                "chunks": [],
                "keep": local == "nonNumeric" and uri in _IX and concept in _COVER,
            }
        )

    def data(chunk: str) -> None:
        if not chunk or not frames:
            return
        if any(frame["local"] == "exclude" and frame["uri"] in _IX for frame in frames):
            return
        for frame in reversed(frames):
            if frame["keep"]:
                frame["chunks"].append(chunk)
                return

    def end(_name: str) -> None:
        if not frames:
            return
        frame = frames.pop()
        if not frame["keep"]:
            return
        value = " ".join("".join(frame["chunks"]).split())
        if not value:
            return
        if frame["concept"] == "EntityRegistrantName":
            names.append(value)
        else:
            symbols.append(value)

    parser = expat.ParserCreate(namespace_separator=_NS)
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = data
    try:
        parser.Parse(text, True)
    except expat.ExpatError as exc:
        raise CoverError("The filing cover could not be read.") from exc
    distinct_names = list(dict.fromkeys(names))
    if not distinct_names:
        raise CoverError("The filing does not state a company name.")
    if len(distinct_names) > 1:
        raise CoverError("The filing states more than one company name.")
    distinct_symbols = list(dict.fromkeys(symbols))
    if not distinct_symbols:
        raise CoverError("The filing does not state a ticker.")
    return Cover(distinct_names[0], tuple(distinct_symbols))


def _plain_date(day: str) -> str:
    year, month, number = day.split("-")
    return f"{_MONTHS[int(month) - 1]} {int(number)}, {year}"


def _copied_days(directory: Path) -> tuple[str, ...]:
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    days: set[str] = set()
    for item in provenance["files"]:
        raw = str(item.get("retrieved_at", ""))
        day = raw[:10]
        if len(day) != 10 or day[4] != "-" or day[7] != "-":
            raise OutputRefused("A saved filing has no save date.")
        days.add(day)
    if not days:
        raise OutputRefused("A saved filing has no save date.")
    return tuple(sorted(days))


def save_sentence(records: list[_Record], companies: tuple[Company, ...]) -> str:
    """Count the filings and companies the page explains, and their copy dates."""
    days = sorted({day for record in records for day in record.copied})
    if not days:
        raise OutputRefused("A saved filing has no save date.")
    when = " and ".join(_plain_date(day) for day in days)
    return (
        f"This page explains {len(records)} saved filings from {len(companies)} companies, "
        f"copied from sec.gov on {when}. It does not look up new filings."
    )


def _records(pinned: Path) -> list[_Record]:
    manifest = json.loads((pinned / "manifest.json").read_text(encoding="utf-8"))
    records: list[_Record] = []
    for entry in manifest["filings"]:
        accession = str(entry["accession"])
        directory = pinned / "filings" / accession
        filing = load_directory(directory)
        if not any(fact.role in MONEY_ROLES for fact in filing.store.facts()):
            continue
        if filing.form not in {"10-K", "10-Q"}:
            raise OutputRefused("A saved filing with figures is not an annual or quarterly report.")
        if not filing.cik or not filing.period_end:
            raise OutputRefused("A saved filing does not state its period.")
        try:
            cover = read_cover(filing.text)
        except CoverError as exc:
            raise OutputRefused(str(exc)) from exc
        records.append(
            _Record(
                accession=accession,
                cik=filing.cik,
                form=filing.form,
                period_end=filing.period_end,
                cover=cover,
                directory=directory,
                copied=_copied_days(directory),
            )
        )
    return records


def companies_from(records: list[_Record]) -> tuple[Company, ...]:
    grouped: dict[str, list[_Record]] = {}
    for record in records:
        grouped.setdefault(record.cik, []).append(record)
    companies: list[Company] = []
    for items in grouped.values():
        latest_day = max(item.period_end for item in items)
        latest = [item for item in items if item.period_end == latest_day]
        if len(latest) != 1:
            raise OutputRefused("Two saved reports for one company end on the same date.")
        chosen = latest[0]
        keys: set[str] = set()
        for item in items:
            keys.add(normalize(item.cover.name))
            for symbol in item.cover.symbols:
                keys.add(normalize(symbol))
        keys.discard("")
        if not keys:
            raise OutputRefused("The filing does not state a company name.")
        companies.append(Company(chosen.cover.name, tuple(sorted(keys)), chosen.accession))
    owner: dict[str, str] = {}
    for company in companies:
        for key in company.keys:
            prior = owner.get(key)
            if prior is not None and prior != company.filing:
                raise OutputRefused("Two saved companies match the same name.")
            owner[key] = company.filing
    companies.sort(key=lambda company: (company.name.casefold(), company.filing))
    return tuple(companies)


def companies_for(pinned: Path) -> tuple[Company, ...]:
    return companies_from(_records(pinned))


def _extra_label(name: str, form: str) -> str:
    kind = {"10-K": "annual report", "10-Q": "quarterly report"}.get(form)
    if kind is None:
        raise OutputRefused("A saved filing with figures is not an annual or quarterly report.")
    return f"{name} ({kind})"


def _buttons(records: list[_Record], companies: tuple[Company, ...]) -> list[tuple[str, str]]:
    """The latest report for each company, then each earlier report with a plain label."""
    by_accession = {record.accession: record for record in records}
    listed: list[tuple[str, str]] = []
    for company in companies:
        chosen = by_accession[company.filing]
        listed.append((company.name, company.filing))
        others = [
            record
            for record in records
            if record.cik == chosen.cik and record.accession != chosen.accession
        ]
        others.sort(key=lambda record: (record.period_end, record.accession), reverse=True)
        for record in others:
            listed.append((_extra_label(record.cover.name, record.form), record.accession))
    return listed


def _as_figure(match: re.Match[str]) -> str:
    href = match.group("href")
    if not href.startswith("https://www.sec.gov/"):
        raise OutputRefused("A figure has no sec.gov source.")
    return (
        f'<a class="figure" data-kind="{match.group("kind")}" data-id="{match.group("id")}" '
        f'href="{href}">{match.group("label")}</a> '
        f'<span class="where">{match.group("title")}</span>'
    )


def _drop_foreign(body: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = match.group(1)
        found = _HREF.search(attrs)
        if found and found.group(1).startswith("https://www.sec.gov/"):
            return match.group(0)
        if 'class="figure"' in attrs:
            raise OutputRefused("A figure has no sec.gov source.")
        return match.group(2)

    return _ANCHOR.sub(replace, body)


def explanation_body(document: str) -> str:
    """The explanation sentences, with each figure linked to its sec.gov source."""
    parts: list[str] = []
    for match in _PARAGRAPH.finditer(document):
        block = match.group(0)
        if 'class="disclaimer"' in block or "Report an error" in block:
            continue
        parts.append(block)
    if not parts:
        raise OutputRefused("The filing explanation has no text.")
    body = _FIGURE.sub(_as_figure, "\n".join(parts))
    if "<data" in body:
        raise OutputRefused("A figure was left without its source.")
    return _drop_foreign(body)


def _heading(form: str) -> str:
    if form == "10-K":
        return "Annual report"
    if form == "10-Q":
        return "Quarterly report"
    raise OutputRefused("A saved filing with figures is not an annual or quarterly report.")


def _script() -> str:
    drop = ",".join(f'"{suffix}":1' for suffix in sorted(SUFFIXES))
    return f"""<script>
(function () {{
  var box = document.getElementById("company");
  var form = document.getElementById("find");
  var note = document.getElementById("nomatch");
  var companies = JSON.parse(document.getElementById("saved-companies").textContent);
  var sections = document.querySelectorAll("section[data-accession]");
  var drop = {{{drop}}};

  function normalize(raw) {{
    var text = String(raw).toLowerCase().replace(/[^0-9a-z]+/g, " ").trim();
    var parts = text ? text.split(/\\s+/) : [];
    while (parts.length > 1 && drop[parts[parts.length - 1]] === 1) {{
      parts.pop();
    }}
    return parts.join(" ");
  }}

  function hideReports() {{
    for (var i = 0; i < sections.length; i++) {{
      sections[i].hidden = true;
    }}
  }}

  function showFiling(accession) {{
    hideReports();
    note.hidden = true;
    var section = document.getElementById("f-" + accession);
    if (!section) {{
      note.hidden = false;
      return;
    }}
    section.hidden = false;
  }}

  form.addEventListener("submit", function (event) {{
    event.preventDefault();
    var key = normalize(box.value);
    var found = [];
    if (key) {{
      for (var i = 0; i < companies.length; i++) {{
        var keys = companies[i].keys;
        for (var j = 0; j < keys.length; j++) {{
          if (keys[j] === key) {{
            found.push(companies[i]);
            break;
          }}
        }}
      }}
    }}
    if (found.length !== 1) {{
      hideReports();
      note.hidden = false;
      return;
    }}
    showFiling(found[0].filing);
  }});

  var buttons = document.querySelectorAll("button[data-filing]");
  for (var n = 0; n < buttons.length; n++) {{
    buttons[n].addEventListener("click", function () {{
      showFiling(this.getAttribute("data-filing"));
    }});
  }}
}}());
</script>"""


_STYLE = """<style>
body {
  margin: 0 auto;
  max-width: 40rem;
  padding: 1.25rem;
  font-family: sans-serif;
  font-size: 20px;
  line-height: 1.5;
  color: #111111;
  background: #ffffff;
}
h1 {
  font-size: 32px;
  line-height: 1.3;
  margin: 0 0 0.5rem;
}
h2 {
  font-size: 26px;
  line-height: 1.3;
}
label {
  display: block;
  font-size: 22px;
  margin-top: 1rem;
}
input, button {
  display: block;
  width: 100%;
  box-sizing: border-box;
  font-size: 22px;
  margin-top: 0.75rem;
  padding: 0.75rem;
  color: #111111;
  background: #ffffff;
  border: 2px solid #111111;
}
button {
  text-align: left;
}
a {
  color: #111111;
  text-decoration: underline;
}
p {
  margin: 1rem 0;
}
.disclaimer {
  font-weight: 700;
}
input:focus, button:focus {
  outline: 3px solid #111111;
  outline-offset: 2px;
}
</style>"""


def _prose(page: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", page, flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = text.replace(DISCLAIMER, " ", 1)
    return re.sub(r"<[^>]+>", " ", text)


def render_page(pinned: Path) -> str:
    records = _records(pinned)
    companies = companies_from(records)
    if not records or not companies:
        raise OutputRefused("No saved filing has figures.")
    sections: list[str] = []
    for record in records:
        filing = load_directory(record.directory)
        body = explanation_body(explain_filing(filing).html)
        sections.append(
            f'<section id="f-{html.escape(record.accession, quote=True)}" '
            f'data-accession="{html.escape(record.accession, quote=True)}" hidden>\n'
            f"<h1>{html.escape(record.cover.name)}</h1>\n"
            f"<h2>{html.escape(_heading(record.form))}</h2>\n"
            f"{body}\n"
            "</section>"
        )
    buttons = "\n".join(
        f'<button type="button" data-filing="{html.escape(filing, quote=True)}">'
        f"{html.escape(label)}</button>"
        for label, filing in _buttons(records, companies)
    )
    payload = json.dumps(
        [
            {"name": company.name, "keys": list(company.keys), "filing": company.filing}
            for company in companies
        ],
        ensure_ascii=True,
    ).replace("<", "\\u003c")
    page = (
        "\ufeff<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        "<title>Filing explanation</title>\n"
        "</head>\n"
        "<body>\n"
        f'<p class="disclaimer">{html.escape(DISCLAIMER)}</p>\n'
        f"<p>{html.escape(save_sentence(records, companies))}</p>\n"
        '<form id="find">\n'
        '<label for="company">Company name or ticker</label>\n'
        '<input id="company" type="text" autocomplete="off">\n'
        '<button type="submit">Explain</button>\n'
        "</form>\n"
        '<p id="nomatch" hidden>No saved filing matches that.</p>\n'
        f'<div id="companies">\n{buttons}\n</div>\n'
        + "\n".join(sections)
        + "\n"
        + _STYLE
        + "\n"
        + f'<script type="application/json" id="saved-companies">{payload}</script>\n'
        + _script()
        + "\n</body>\n</html>\n"
    )
    ensure_safe_output(page)
    reason = advice_reason(_prose(page))
    if reason:
        raise OutputRefused(reason)
    return page


def build_page(output: Path, pinned: Path | None = None) -> Path:
    """Write the page. The file is created only after the checks pass."""
    page = render_page(pinned or pinned_dir())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output
