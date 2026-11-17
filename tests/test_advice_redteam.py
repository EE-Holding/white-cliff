from white_cliff.advice import advice_reason, classifier_reason, rule_list_reason
from white_cliff.pipeline import explain_filing, load_directory
from tests.support import MINI_XML, write_filing
from tests.test_model_numbers import NUMBER_WORDS
from tests.test_no_price_metrics import PRICE_PHRASES

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
    "Investors should accumulate shares",
    "We rate the shares overweight",
    "strong upside",
    "a bargain",
    "Consider buying the shares",
    "Investors should consider selling",
    "attractively priced",
    "Go long the stock",
    "Take profits now",
    "Trim the position",
    "Avoid the stock",
    "a screaming opportunity",
    "Revenue is expected to grow next year",
    "Management expects margins to expand",
    "The shares should rally",
    "Earnings will likely improve",
    "Kaufempfehlung",
    "unterbewertet",
    "Achetez",
    "sous-évaluée",
    "Compre",
    "infravalorada",
    "ʙᴜʏ",
    "b_u_y",
    "b\u03c5y the stock",
    "We recommend purchasing the shares",
    "The shares look underpriced.",
    "The shares look overpriced.",
    "The shares look mispriced.",
    "This is a good investment.",
    "This is a compelling investment.",
    "This is a steal.",
    "This is a must-own name.",
    "Own the stock.",
    "Dump the stock.",
    "Exit the position.",
    "Load up on the shares.",
    "Snap up the shares.",
    "Pick up shares on weakness.",
    "We upgrade the shares.",
    "We downgrade the shares.",
    "This is our top pick.",
    "Our recommendation is positive.",
    "The shares merit a positive rating.",
    "Investors may wish to add to their positions.",
    "Investors are advised to add exposure.",
    "It is a good time to add to your position.",
    "Stay away from the shares.",
    "The intrinsic value exceeds the quote.",
    "The valuation looks rich.",
    "The shares look inexpensive.",
    "b\u028ay",
    "b\u1969y",
    "\u13cfuy",
    "b/u/y",
    "Die Aktie ist überbewertet.",
    "Die Aktie ist günstig.",
    "Koop het aandeel.",
    "Beleggers moeten kopen.",
    "Покупайте акции.",
    "Acquistate le azioni.",
    "株を買うべき",
    "买入该股票",
    "Kupuj akcje.",
    "Satın al.",
    "La acción está barata.",
    "Revenue is projected to grow.",
    "Revenue is set to grow.",
    "Revenue is set to rise.",
    "The shares are poised to rise.",
    "The shares are poised to jump.",
    "Revenue is going to grow next year.",
    "The business is on track to expand.",
    "Earnings are predicted to increase.",
    "The shares are bound to rise.",
    "Revenue may increase next year.",
    "Next year revenue grows.",
    "The company is guided to grow.",
    "Revenue is projected to climb.",
    "We predict higher earnings.",
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


def test_adversarial_text_cannot_reach_rendered_output(tmp_path):
    from white_cliff.numbers import number_words
    from white_cliff.prices import price_metric_reason

    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    explained = explain_filing(load_directory(directory))
    rendered = (explained.markdown + "\n" + explained.html).casefold()
    for text in (*ADVERSARIAL, *NUMBER_WORDS, *PRICE_PHRASES):
        caught = (
            advice_reason(text)
            or number_words(text)
            or price_metric_reason(text)
        )
        if caught:
            continue
        assert text.casefold() not in rendered, text


def test_blocked_section_is_omitted_and_not_softened(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000100000001/mini.xml"
    directory = write_filing(tmp_path / "mini", "mini.xml", MINI_XML, url)
    filing = load_directory(directory)
    sentence = "You should buy this stock. [section:Income statement]."
    assert advice_reason(sentence)
    explained = explain_filing(filing)
    assert "You should buy this stock." not in explained.markdown
    assert "You should buy this stock." not in explained.html
