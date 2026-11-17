from white_cliff.advice import advice_reason, classifier_reason, rule_list_reason
from white_cliff.pipeline import explain_filing, load_directory
from tests.support import MINI_XML, write_filing

ADVERSARIAL = [
    "You should buy this stock.",
    "Buy.",
    "Sell now.",
    "This is a hold.",
    "Strong buy.",
    "Price target of 150.",
    "The shares are undervalued.",
    "The shares are over-valued.",
    "The stock is cheap.",
    "The stock is expensive.",
    "Fair value is above the price.",
    "Cheap versus peers.",
    "We forecast revenue will rise.",
    "The price will increase.",
    "b u y",
    "s e l l",
    "y\u200bou should buy",
    "Вuy now",
    "ｂｕｙ",
    "bu\ny",
    "you\u00a0should act",
    "p r i c e t a r g e t",
    "Deberías comprar estas acciones.",
    "Recomiendo vender.",
    "Il faut acheter.",
    "Vous devriez vendre.",
    "Sie sollten kaufen.",
    "建议买入",
    "应该持有",
    "you ought to acquire shares",
]

BENIGN = [
    "Revenue for the fiscal year was {fact:abcdefghijklmnop} [section:Income statement].",
    "The filing reports cash and debt [section:Balance sheet].",
    "Operating cash flow for the reported period was {fact:abcdefghijklmnop} [section:Cash flows].",
    "The withholding is described in the filing [section:Notes].",
]


def test_advice_redteam_blocks_every_adversarial_string():
    for text in ADVERSARIAL:
        reason = advice_reason(text)
        assert reason, text
        assert rule_list_reason(text) or classifier_reason(text)


def test_benign_filing_language_is_not_advice():
    for text in BENIGN:
        assert advice_reason(text) is None, text


def test_blocked_section_is_omitted_and_not_softened(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    explained = explain_filing(
        filing,
        model_text="You should buy this stock. [section:Income statement].",
    )
    assert "You should buy this stock." not in explained.markdown
    assert "You should buy this stock." not in explained.html
    assert "advice" in explained.markdown
    assert explained.reasons
