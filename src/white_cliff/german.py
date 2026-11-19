"""German numbers, dates, and the German forbidden-word gate.

Numbers are formatted from the stored value. Nothing here rewrites English text.
"""

from __future__ import annotations

import html
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

NBSP = "\u00a0"
MINUS = "\u2212"

MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

_SCALE = {"millions": "Mio.", "thousands": "Tsd.", "billions": "Mrd."}

# The patterns from the cleared German wording, section 5. Whole-string exemptions
# are applied by the caller before these run.
_PATTERNS = (
    r"\bkauf\w*",
    r"\bgekauft\w*",
    r"\bverkauf\w*",
    r"\bverkauft\w*",
    r"\bhalten\b",
    r"\bhält\b",
    r"\bhielt\w*",
    r"\bgehalten\w*",
    r"\bhalte\w*",
    r"\bkaufempfehlung\w*",
    r"\bempfehl\w*",
    r"\bempfiehl\w*",
    r"\bempfohl\w*",
    r"\bkursziel\w*",
    r"\bziel\b",
    r"\bzielwert\w*",
    r"\bunterbewertet\w*",
    r"\büberbewertet\w*",
    r"\bbewertung\w*",
    r"\bfair\w* wert\w*",
    r"\bbillig\w*",
    r"\bteuer\w*",
    r"\bgünstig\w*",
    r"\bschnäppchen\w*",
    r"\bchance\w*",
    r"\bgelegenheit\w*",
    r"\blohn\w* sich\b",
    r"\blohnend\w*",
    r"\banlagetipp\w*",
    r"\btipp\w*",
    r"\banlageempfehlung\w*",
    r"\brendite\w*",
    r"\bkurs\b",
    r"\bkurse\w*",
    r"\baktienkurs\w*",
    r"\bkurspotenzial\w*",
    r"\bpotenzial\w*",
    r"\baufwärtspotenzial\w*",
    r"\babwärtsrisik\w*",
    r"\bmeiden\b",
    r"\bvermeiden\b",
    r"\bsichere anlage\w*",
    r"\brisikolos\w*",
    r"\briskante anlage\w*",
    r"\bsie sollten\b",
    r"\bsollte\w*",
    r"\bsollen\b",
    r"\bdu\b",
    r"\bdein\w*",
    r"\bmarktkapitalisierung\w*",
    r"\bkgv\b",
    r"\bkurs-gewinn-verhältnis\w*",
    r"\bdividendenrendite\w*",
    r"\bkurs-buchwert\w*",
    r"\bev/ebitda\b",
    r"\banleger\w*",
    r"\binvestor\w*",
    r"\bder markt\b",
    r"\bdes marktes\b",
    r"\bfür sie\b",
    r"\bwird\s+(\w+\s+){0,3}(steigen|sinken|fallen|wachsen|zunehmen|abnehmen|liegen|erreichen|übertreffen)\b",
    r"\bwerden\s+(\w+\s+){0,3}(steigen|sinken|fallen|wachsen)\b",
    r"\bprognos\w*",
    r"\bvoraussichtlich\w*",
    r"\berwart\w*",
    r"\bunerwart\w*",
    r"\bausblick\w*",
    r"\bkünftig\w*",
    r"\bzukünftig\w*",
    r"\bdürfte\w*",
    r"\bwahrscheinlich\w*",
    r"\bauf kurs\b",
    r"\bauf dem weg zu\b",
    r"\bdemnächst\b",
    r"\bguidance\b",
    r"\bkonsens\w*",
    r"\bschätzung\w*",
    r"\bgut\b",
    r"\bgute[nrsm]?\b",
    r"\bbesser\w*",
    r"\bbeste[nrsm]?\b",
    r"\bschlecht\w*",
    r"\bstark\w*",
    r"\bstärk\w*",
    r"\bschwach\w*",
    r"\bschwäch\w*",
    r"\bgesund\w*",
    r"\bungesund\w*",
    r"\bsolide\w*",
    r"\brobust\w*",
    r"\bbesorgniserregend\w*",
    r"\bbeunruhig\w*",
    r"\balarm\w*",
    r"\bwarn\w*",
    r"\bbedenk\w*",
    r"\bsorge\w*",
    r"\brekord\w*",
    r"\beinbruch\w*",
    r"\beinbrüch\w*",
    r"\beingebrochen\w*",
    r"\babsturz\w*",
    r"\babgestürzt\w*",
    r"\bboom\w*",
    r"\berholung\w*",
    r"\berholt\w*",
    r"\bpositiv\w*",
    r"\bnegativ\w*",
    r"\bwachstum\w*",
    r"\bwuchs\w*",
    r"\bgewachsen\w*",
    r"\bwächst\b",
    r"\bzuwachs\w*",
    r"\beinbuße\w*",
    r"\bein plus\b",
    r"\bein minus\b",
    r"\bbeeindruck\w*",
    r"\büberrasch\w*",
    r"\berfreulich\w*",
    r"\bleider\b",
    r"\bbedauerlich\w*",
    r"\berstaunlich\w*",
    r"\bergebnisqualität\b",
    r"\bvertrauenswürdig\w*",
    r"\bverlässlich\w*",
    r"\bzuverlässig\w*",
    r"\bunzuverlässig\w*",
    r"\bgutes zeichen\b",
    r"\bschlechtes zeichen\b",
    r"\bdas bedeutet\b",
    r"\bdies deutet\b",
    r"\bdeutet darauf hin\b",
    r"\blässt vermuten\b",
    r"\bspricht für\b",
    r"\brisik\w*",
    r"\bscore\w*",
    r"\bpunktzahl\w*",
    r"\bnote\b",
    r"\bnoten\b",
    r"\bbenotung\w*",
    r"\brating\w*",
    r"\branking\w*",
    r"\brangliste\w*",
    r"\bampel\w*",
    r"\bgesundheit\w*",
    r"\bsauber\w*",
    r"\bschmutzig\w*",
    r"\breal\w*",
    r"\bwahre[nrsm]?\b",
    r"\bwahr\b",
    r"\bkünstlich\w*",
    r"\bdeutlich\w*",
    r"\bkräftig\w*",
    r"\bmassiv\w*",
    r"\bdrastisch\w*",
    r"\bdramatisch\w*",
    r"\bsprunghaft\w*",
    r"\brasant\w*",
    r"\bsteil\w*",
    r"\benorm\w*",
    r"\berheblich\w*",
    r"\bnur\b",
    r"\blediglich\b",
    r"\bbloß\b",
    r"\bgewinner\w*",
    r"\bverlierer\w*",
    r"\bspitzenreiter\w*",
    r"\bmarktführer\w*",
    r"\bführend\w*",
    r"\bnachzügler\w*",
    r"\bschlusslicht\w*",
    r"\bschlägt\b",
    r"\bschlug\b",
    r"\bübertr[iao]f\w*",
    r"\bverfehl\w*",
    r"\bhinkt\w*",
    r"\boutperform\w*",
    r"\bunderperform\w*",
    r"\bspitze\b",
    r"\btop\b",
    r"\bvorne\b",
    r"\bklassenbest\w*",
    r"\bbetrug\w*",
    r"\bbetrüg\w*",
    r"\bmanipul\w*",
    r"\bgeschönt\w*",
    r"\bschönfärb\w*",
    r"\bfrisiert\w*",
    r"\bgeschminkt\w*",
    r"\baufgebläht\w*",
    r"\bbilanztrick\w*",
    r"\bbilanzkosmetik\w*",
    r"\bbilanzpolitik\w*",
    r"\bergebnissteuerung\w*",
    r"\baggressive\w* bilanzierung\w*",
    r"\bkreative\w* buchführung\w*",
    r"\bverdächtig\w*",
    r"\bverdacht\w*",
    r"\bfragwürdig\w*",
    r"\bzweifelhaft\w*",
    r"\bunregelmäßig\w*",
    r"\brote flagge\w*",
    r"\bwarnsignal\w*",
    r"\bzu schön, um wahr zu sein\b",
    r"\bverschleier\w*",
    r"\bverheimlich\w*",
    r"\bversteck\w*",
    r"\bverborgen\w*",
    r"\birreführ\w*",
    r"\bfalsch dargestellt\w*",
    r"\bbenford\w*",
    r"\bbeneish\w*",
    r"\bm-score\w*",
    r"\bnicht durch zahlungen gedeckt\b",
    r"\bnicht durch cash gedeckt\b",
    r"\bkanalfüllung\b",
    r"\babschreibung steht bevor\b",
)

_COMPILED = tuple(re.compile(pattern.casefold()) for pattern in _PATTERNS)

_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\ufeff\u2060"), None)

# Letters that look like Latin letters. Folded after casefold, so the keys are lowercase.
_HOMO = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ѕ": "s",
        "һ": "h",
        "ј": "j",
        "ο": "o",
        "α": "a",
        "ν": "v",
        "τ": "t",
        "κ": "k",
    }
)


def german_number(value: Decimal, places: int | None = None) -> str:
    """Group thousands with a full stop and decimals with a comma."""
    negative = value < 0
    number = abs(value)
    if places is not None:
        quantum = Decimal(1).scaleb(-places)
        number = number.quantize(quantum, rounding=ROUND_HALF_UP)
        text = f"{number:.{places}f}"
    else:
        text = format(number, "f")
        if "." in text:
            whole, frac = text.split(".", 1)
            frac = frac.rstrip("0")
            text = whole + (("." + frac) if frac else "")
    if "." in text:
        whole, frac = text.split(".", 1)
    else:
        whole, frac = text, ""
    groups: list[str] = []
    rest = whole or "0"
    while rest:
        groups.append(rest[-3:])
        rest = rest[:-3]
    body = ".".join(reversed(groups))
    if frac:
        body += "," + frac
    if negative:
        body = MINUS + body
    return body


def german_date(iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{day}.{NBSP}{MONTHS[month - 1]}{NBSP}{year}"


def format_measure(value: Decimal, unit: str) -> str:
    """A measure from its stored value and unit. The scale word is taken from anywhere in the unit."""
    text = " ".join(unit.split())
    if text == "percent":
        return german_number(value, 1) + NBSP + "Prozent"
    if text == "percentage points":
        return german_number(value, 1) + NBSP + "Prozentpunkte"
    per_share = "USD/shares" in text
    if per_share:
        text = text.replace("USD/shares", "USD")
    currency = ""
    scale = ""
    kind = ""
    for part in text.split():
        low = part.lower()
        if low in _SCALE and not scale:
            scale = low
        elif part.upper() == "USD" and not currency:
            currency = "USD"
        elif low == "shares":
            kind = "shares"
    number = german_number(value, None)
    bits = [number]
    if scale:
        bits.append(_SCALE[scale])
    if currency:
        bits.append(currency)
    if per_share:
        bits.append("je Aktie")
    elif kind == "shares":
        bits.append("Aktien")
    return NBSP.join(bits)


def format_raw(raw: str) -> str:
    """Format a stored 'digits unit' label. Leave any other text untouched."""
    text = " ".join(html.unescape(raw).replace(NBSP, " ").split())
    per = re.fullmatch(
        r"(-?\d+(?:\.\d+)?)\s+USD/shares(?:\s+(millions|thousands|billions))?$",
        text,
        re.I,
    )
    if per:
        scale = f" {per.group(2)}" if per.group(2) else ""
        return format_measure(Decimal(per.group(1)), "USD/shares" + scale)
    money = re.fullmatch(
        r"(-?\d+(?:\.\d+)?)(?:\s+(USD))?(?:\s+(millions|thousands|billions))?$",
        text,
        re.I,
    )
    if money and money.group(2):
        scale = f" {money.group(3)}" if money.group(3) else ""
        return format_measure(Decimal(money.group(1)), "USD" + scale)
    parts = text.split()
    if not parts or re.fullmatch(r"-?\d+(?:\.\d+)?", parts[0]) is None:
        return text
    scale = ""
    rest: list[str] = []
    for part in parts[1:]:
        if part.lower() in _SCALE and not scale:
            scale = part.lower()
        else:
            rest.append(part)
    unit = " ".join(rest + ([scale] if scale else []))
    return format_measure(Decimal(parts[0]), unit or "shares")


def prepare(text: str) -> str:
    """Lower-case, NFKC, drop invisible characters, fold lookalikes, join spaced letters."""
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.translate(_INVISIBLE)
    folded = folded.casefold()
    folded = folded.translate(_HOMO)

    def collapse(match: re.Match[str]) -> str:
        return match.group(1).replace(" ", "")

    return re.sub(r"(?<!\w)((?:\w ){2,}\w)(?!\w)", collapse, folded)


def german_hit(text: str) -> str | None:
    """The first forbidden German pattern in prepared text, or None."""
    prepared = prepare(text)
    for pattern in _COMPILED:
        found = pattern.search(prepared)
        if found:
            return found.group(0)
    return None
