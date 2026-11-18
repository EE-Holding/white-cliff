"""A per-share amount keeps the words per share. A bare dollar amount does not."""

import re
from decimal import Decimal

from tests.support import make_fact
from white_cliff.present import shown_amount
from white_cliff.render import _measure_label
from white_cliff.wording import _link_fact, _parts_html, show_measure


def test_bare_dollars_stay_bare_and_per_share_says_per_share():
    assert shown_amount("1.64 USD") == "$1.64"
    assert "per share" not in shown_amount("1.64 USD")
    per_share = shown_amount("1.64 USD/shares")
    assert per_share == "$1.64 per share"
    assert re.search(r"\$1\.64(?!\s+per share)", per_share) is None
    scaled = shown_amount("1.64 USD/shares millions")
    assert scaled == "$1.64 million per share"
    assert "per share" in scaled


def test_a_per_share_sentence_fails_without_the_words():
    fact = make_fact(
        "1.64",
        unit="USD/shares",
        concept="EarningsPerShareDiluted",
        role="per_share",
    )
    sentence = _parts_html(
        "E2",
        [("text", "Earnings per share was "), _link_fact(fact), ("text", ".")],
    )
    assert show_measure(Decimal("1.64"), "USD/shares") == "$1.64 per share"
    assert _measure_label(Decimal("1.64"), "USD/shares") == "$1.64 per share"
    assert "$1.64 per share" in sentence
    assert re.search(r"\$1\.64(?!\s+per share)", sentence) is None
