import os
import subprocess
import sys
from pathlib import Path

from white_cliff.advice import advice_reason, classifier_reason, rule_list_reason
from white_cliff.pipeline import explain_filing, load_directory
from tests.support import MINI_XML, write_filing

ROOT = Path(__file__).resolve().parents[1]

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


def test_model_command_cannot_place_advice_in_the_output(tmp_path):
    script = tmp_path / "stub_model.py"
    script.write_text(
        "import os, sys\nsys.stdout.write(os.environ['STUB_TEXT'])\n",
        encoding="utf-8",
    )
    filing = ROOT / "tests" / "fixtures" / "omissions"
    for text in ADVERSARIAL:
        env = os.environ.copy()
        env["WHITE_CLIFF_USER_AGENT"] = "Example Name name@example.com"
        env["WHITE_CLIFF_CONFIG"] = str(tmp_path / "missing.toml")
        env["PYTHONPATH"] = str(ROOT / "src")
        env["WHITE_CLIFF_MODEL_CMD"] = f"{sys.executable} {script}"
        env["STUB_TEXT"] = text
        completed = subprocess.run(
            [sys.executable, "-m", "white_cliff", "explain", str(filing)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        combined = completed.stdout + completed.stderr
        assert text not in combined, text


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
