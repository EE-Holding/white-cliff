import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_personal_features_are_refused(tmp_path):
    env = os.environ.copy()
    env["WHITE_CLIFF_USER_AGENT"] = "Example Name name@example.com"
    env["WHITE_CLIFF_CONFIG"] = str(tmp_path / "missing.toml")
    env["HOME"] = str(tmp_path)
    target = ROOT / "tests" / "fixtures" / "omissions"
    for flag in ("--watchlist", "--holdings", "--alerts", "--rank", "--screen", "--profile"):
        completed = subprocess.run(
            [sys.executable, "-m", "white_cliff", "explain", str(target), flag],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert completed.returncode != 0, flag
        assert "123-45-6789" not in completed.stdout
    names = {path.name for path in tmp_path.rglob("*")}
    for banned in ("watchlist", "holdings", "profile", "alerts"):
        assert banned not in names
