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


def _local(env: dict[str, str]) -> dict[str, str]:
    env.pop("GITHUB_ACTIONS", None)
    env.pop("AUTHOR_NAME", None)
    return env


def test_ci_workflow_needs_no_variables_or_secrets():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "vars." not in text
    assert "secrets." not in text
    assert "AUTHOR_EMAIL" not in text
    assert "AUTHOR_NAME" not in text


def test_expected_email_comes_from_the_environment(tmp_path):
    env = _local(_env("Erik Eicke", "ada@example.com"))
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


def test_ci_checks_the_name_and_ignores_the_email(tmp_path):
    env = _env("Erik Eicke", "one@example.com")
    env["GIT_AUTHOR_EMAIL"] = "one@example.com"
    env["GIT_COMMITTER_EMAIL"] = "two@example.org"
    env["GITHUB_ACTIONS"] = "true"
    env.pop("AUTHOR_NAME", None)
    env.pop("AUTHOR_EMAIL", None)
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
    assert "repository variable" not in completed.stdout + completed.stderr


def test_ci_rejects_a_different_name_and_any_trailer(tmp_path):
    env = _env("Other Person", "other@example.com")
    env["GITHUB_ACTIONS"] = "true"
    env.pop("AUTHOR_NAME", None)
    env.pop("AUTHOR_EMAIL", None)
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

    named = _env("Erik Eicke", "ada@example.net")
    named["GITHUB_ACTIONS"] = "true"
    named.pop("AUTHOR_EMAIL", None)
    other = tmp_path / "trailer"
    other.mkdir()
    subprocess.check_call(["git", "init"], cwd=other, env=named)
    _commit(other, named, "Add a note\n\nCo-authored-by: Pat Example <pat@example.com>")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=other,
        env=named,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0


def test_local_identity_falls_back_to_git_config(tmp_path):
    env = _local(_env("Erik Eicke", "local@example.net"))
    env.pop("AUTHOR_EMAIL", None)
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
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
    env = _local(_env("Erik Eicke", "ada@example.com"))
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
    env = _local(_env("Other Person", "other@example.com"))
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

    good = _local(_env("Erik Eicke", "ada@example.com"))
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
    mismatched = good.copy()
    mismatched["GIT_AUTHOR_EMAIL"] = "other@example.org"
    mismatched["GIT_COMMITTER_EMAIL"] = "other@example.org"
    (tmp_path / "clean.txt").write_text("Add a note\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--commit-msg", str(tmp_path / "clean.txt")],
        cwd=tmp_path,
        env=mismatched,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert HOOK.is_file()
