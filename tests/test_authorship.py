import os
import re
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


_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_ALLOWED_HOSTS = {"example.com", "example.org", "example.net"}


def test_tracked_files_contain_no_email_address():
    listed = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    offenders: list[str] = []
    for name in listed.splitlines():
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        for match in _EMAIL.finditer(text):
            host = match.group(0).rsplit("@", 1)[1].lower()
            if host not in _ALLOWED_HOSTS:
                offenders.append(f"{name}: {match.group(0)}")
    assert offenders == []


def test_expected_identity_comes_from_the_environment(tmp_path):
    env = _env("Ada Example", "ada@example.com")
    env["AUTHOR_NAME"] = "Ada Example"
    env["AUTHOR_EMAIL"] = "ada@example.com"
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


def test_ci_fails_when_the_repository_variable_is_missing(tmp_path):
    env = os.environ.copy()
    env["GITHUB_ACTIONS"] = "true"
    env.pop("AUTHOR_NAME", None)
    env.pop("AUTHOR_EMAIL", None)
    env["GIT_AUTHOR_NAME"] = "Ada Example"
    env["GIT_AUTHOR_EMAIL"] = "ada@example.com"
    env["GIT_COMMITTER_NAME"] = "Ada Example"
    env["GIT_COMMITTER_EMAIL"] = "ada@example.com"
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
    _commit(tmp_path, env, "Add a note")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    text = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "repository variable" in text
    assert "AUTHOR_EMAIL" in text


def test_local_identity_falls_back_to_git_config(tmp_path):
    env = os.environ.copy()
    env.pop("AUTHOR_NAME", None)
    env.pop("AUTHOR_EMAIL", None)
    env.pop("GITHUB_ACTIONS", None)
    env["GIT_AUTHOR_NAME"] = "Local Example"
    env["GIT_AUTHOR_EMAIL"] = "local@example.net"
    env["GIT_COMMITTER_NAME"] = "Local Example"
    env["GIT_COMMITTER_EMAIL"] = "local@example.net"
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
    subprocess.check_call(["git", "config", "user.name", "Local Example"], cwd=tmp_path, env=env)
    subprocess.check_call(["git", "config", "user.email", "local@example.net"], cwd=tmp_path, env=env)
    _commit(tmp_path, env, "Add a note")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_authorship_script_accepts_the_required_identity(tmp_path):
    env = _env("Ada Example", "ada@example.com")
    env["AUTHOR_NAME"] = "Ada Example"
    env["AUTHOR_EMAIL"] = "ada@example.com"
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
    env["AUTHOR_NAME"] = "Ada Example"
    env["AUTHOR_EMAIL"] = "ada@example.com"
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

    good = _env("Ada Example", "ada@example.com")
    good["AUTHOR_NAME"] = "Ada Example"
    good["AUTHOR_EMAIL"] = "ada@example.com"
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
    message.write_text("Add a note\n\nSigned-off-by: Ada Example <ada@example.com>\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--commit-msg", str(message)],
        cwd=tmp_path,
        env=good,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert "trailer" in completed.stdout + completed.stderr
    assert HOOK.is_file()
