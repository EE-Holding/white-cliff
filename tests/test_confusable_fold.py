"""The confusable fold keeps the same characters when it scans ASCII in slices."""

from white_cliff.quotes import _fold_with_map
from white_cliff.skeleton import fold_confusable


def test_ascii_text_casefolds_without_the_digit_map():
    assert fold_confusable("Market Cap 100%") == "market cap 100%"
    assert fold_confusable('Say "Hi" 01') == 'say "hi" 01'
    assert fold_confusable("plain") == "plain"


def test_a_mark_and_a_format_character_are_dropped():
    assert fold_confusable("e\u0301\u200bX") == "ex"


def test_the_quote_map_records_the_source_index():
    text, origins = _fold_with_map("Market Cap 100%")
    assert text == "rnarket cap lOO\u00b0/\u2080"
    assert list(origins) == [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 14, 14]
    text, origins = _fold_with_map('Say "Hi" 01')
    assert text == "say ''hi'' Ol"
    assert list(origins) == [0, 1, 2, 3, 4, 4, 5, 6, 7, 7, 8, 9, 10]
    text, origins = _fold_with_map("e\u0301\u200bX")
    assert text == "ex"
    assert list(origins) == [0, 3]
    text, origins = _fold_with_map("plain")
    assert text == "plain"
    assert list(origins) == [0, 1, 2, 3, 4]
