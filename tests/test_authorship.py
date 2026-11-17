import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_authorship.py"
HOOK = ROOT / "scripts" / "commit-msg"


def _env(name: str, email: str) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = name
    env["GIT_AUTHOR_EMAIL"] = email
    env["GIT_COMMITTER_NAME"] = name
    env["GIT_COMMITTER_EMAIL"] = email
    return env


def _commit(repo: Path, env: dict[str, str], message: str) -> None:
    (repo / "note.txt").write_text("note\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "note.txt"], cwd=repo, env=env)
    subprocess.check_call(["git", "commit", "-m", message], cwd=repo, env=env)


def test_authorship_script_accepts_the_required_identity(tmp_path):
    env = _env("Erik Eicke", "eickeerik@gmail.com")
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
    _commit(tmp_path, env, "Add a note")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_authorship_script_rejects_other_identities_and_trailers(tmp_path):
    env = _env("Other Person", "other@example.com")
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
    _commit(tmp_path, env, "Add a note")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0

    good = _env("Erik Eicke", "eickeerik@gmail.com")
    other = tmp_path / "trailer"
    other.mkdir()
    subprocess.check_call(["git", "init"], cwd=other, env=good)
    _commit(other, good, "Add a note\n\nCo-authored-by: Pat Example <pat@example.com>")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=other,
        env=good,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    message = tmp_path / "message.txt"
    message.write_text("Add a note\n\nSigned-off-by: Erik Eicke <eickeerik@gmail.com>\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--commit-msg", str(message)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert HOOK.is_file()
