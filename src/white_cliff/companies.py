"""Resolve a ticker or company name, then pick the latest 10-K or 10-Q."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from typing import Sequence

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_FORMS = frozenset({"10-K", "10-Q"})
_SUFFIXES = (
    " incorporated",
    " corporation",
    " company",
    " limited",
    " inc",
    " corp",
    " co",
    " ltd",
    " plc",
    " llc",
    " lp",
)
_SUFFIX_WORDS = frozenset(suffix.strip() for suffix in _SUFFIXES)
_CUTOFF = 0.8


@dataclass(frozen=True)
class Company:
    cik: str
    ticker: str
    title: str


@dataclass(frozen=True)
class OneMatch:
    company: Company


@dataclass(frozen=True)
class SeveralMatches:
    companies: tuple[Company, ...]


@dataclass(frozen=True)
class NoMatch:
    close: tuple[Company, ...]


@dataclass(frozen=True)
class PeriodicFiling:
    form: str
    filed: str
    period: str
    accession: str
    cik: str
    document: str

    @property
    def url(self) -> str:
        cik_path = str(int(self.cik))
        nodash = self.accession.replace("-", "")
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{cik_path}/{nodash}/{self.document}"
        )


def submissions_url(cik: str) -> str:
    digits = "".join(char for char in str(cik) if char.isdigit())
    if not digits or len(digits) > 10:
        raise ValueError("cik")
    return f"https://data.sec.gov/submissions/CIK{digits.zfill(10)}.json"


def normalize_name(value: str) -> str:
    text = value.casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def core_name(value: str) -> str:
    name = normalize_name(value)
    changed = True
    while changed and name:
        changed = False
        for suffix in _SUFFIXES:
            if name.endswith(suffix) and name != suffix.strip():
                name = name[: -len(suffix)].strip()
                changed = True
                break
    return name


def parse_tickers(payload: bytes) -> tuple[Company, ...]:
    data = json.loads(payload)
    rows = data.values() if isinstance(data, dict) else data
    companies: list[Company] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        title = str(row.get("title") or "").strip()
        raw_cik = row.get("cik_str", row.get("cik", ""))
        digits = "".join(char for char in str(raw_cik) if char.isdigit())
        if not ticker or not title or not digits or len(digits) > 10:
            continue
        companies.append(Company(cik=digits.zfill(10), ticker=ticker, title=title))
    return tuple(companies)


def _ordered(companies: Sequence[Company]) -> tuple[Company, ...]:
    rows = sorted(companies, key=lambda company: (company.title.casefold(), company.ticker.casefold()))
    return tuple(rows[:8])


def _one_or_several(companies: Sequence[Company]) -> OneMatch | SeveralMatches:
    chosen = _ordered(companies)
    if len(chosen) == 1:
        return OneMatch(chosen[0])
    return SeveralMatches(chosen)


def _close(query: str, companies: Sequence[Company]) -> tuple[Company, ...]:
    needle = core_name(query) or normalize_name(query)
    if not needle:
        return ()
    scored: list[tuple[float, Company]] = []
    folded = query.casefold()
    for company in companies:
        hay = core_name(company.title) or normalize_name(company.title)
        score = difflib.SequenceMatcher(None, needle, hay).ratio()
        ticker_score = difflib.SequenceMatcher(None, folded, company.ticker.casefold()).ratio()
        best = max(score, ticker_score)
        if best >= _CUTOFF:
            scored.append((best, company))
    scored.sort(key=lambda item: (-item[0], item[1].title.casefold(), item[1].ticker.casefold()))
    return tuple(company for _score, company in scored[:8])


def resolve_company(query: str, companies: Sequence[Company]) -> OneMatch | SeveralMatches | NoMatch:
    raw = " ".join(query.split())
    if not raw:
        return NoMatch(())
    folded = raw.casefold()
    ticker_hits = [company for company in companies if company.ticker.casefold() == folded]
    if ticker_hits:
        return _one_or_several(ticker_hits)
    norm = normalize_name(raw)
    exact = [company for company in companies if normalize_name(company.title) == norm]
    if exact:
        return _one_or_several(exact)
    prefix = [
        company
        for company in companies
        if normalize_name(company.title).startswith(norm + " ")
    ]
    if prefix:
        return _one_or_several(prefix)
    if norm not in _SUFFIX_WORDS:
        needle = core_name(raw)
        if needle and needle not in _SUFFIX_WORDS:
            cores = [company for company in companies if core_name(company.title) == needle]
            if cores:
                return _one_or_several(cores)
    return NoMatch(_close(raw, companies))


def select_latest(payload: dict, cik: str) -> PeriodicFiling | None:
    recent = {}
    filings = payload.get("filings") if isinstance(payload, dict) else None
    if isinstance(filings, dict) and isinstance(filings.get("recent"), dict):
        recent = filings["recent"]
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    periods = recent.get("reportDate") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []
    if not isinstance(forms, list):
        return None
    digits = "".join(char for char in str(cik) if char.isdigit()).zfill(10)
    best: PeriodicFiling | None = None
    best_date = ""
    for index, form in enumerate(forms):
        if form not in _FORMS:
            continue
        if index >= len(dates) or index >= len(accessions) or index >= len(documents):
            continue
        filed = str(dates[index])
        period = str(periods[index]) if index < len(periods) else ""
        accession = str(accessions[index])
        document = str(documents[index])
        if _ACCESSION.fullmatch(accession) is None or _SAFE_NAME.fullmatch(document) is None:
            continue
        if best is None or filed > best_date:
            best_date = filed
            best = PeriodicFiling(
                form=str(form),
                filed=filed,
                period=period,
                accession=accession,
                cik=digits,
                document=document,
            )
    return best
