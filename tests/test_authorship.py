import gzip
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
        data = (ROOT / name).read_bytes()
        # A compressed fixture is text after inflation. The packed bytes are not an address.
        if data.startswith(b"\x1f\x8b"):
            data = gzip.decompress(data)
        text = data.decode("utf-8", errors="replace")
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


def _install_hook(repo: Path) -> Path:
    destination = repo / "scripts"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("check_authorship.py", "pre-push"):
        target = destination / name
        target.write_bytes((ROOT / "scripts" / name).read_bytes())
    hook = destination / "pre-push"
    hook.chmod(0o755)
    return hook


def test_pre_push_hook_requires_the_configured_email(tmp_path):
    assert (ROOT / "scripts" / "pre-push").is_file()
    env = _local(_env("Erik Eicke", "ada@example.com"))
    env["AUTHOR_EMAIL"] = "ada@example.com"
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
    hook = _install_hook(tmp_path)
    _commit(tmp_path, env, "Add a note")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    completed = subprocess.run(
        ["sh", str(hook), "origin", "https://example.com/white-cliff.git"],
        cwd=tmp_path,
        env=env,
        input=f"refs/heads/skeleton {head} refs/heads/skeleton {'0' * 40}\n",
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    bad = _local(_env("Erik Eicke", "other@example.org"))
    bad["AUTHOR_EMAIL"] = "ada@example.com"
    other = tmp_path / "other"
    other.mkdir()
    subprocess.check_call(["git", "init"], cwd=other, env=bad)
    other_hook = _install_hook(other)
    _commit(other, bad, "Add a note")
    bad_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=other, text=True).strip()
    completed = subprocess.run(
        ["sh", str(other_hook), "origin", "https://example.com/white-cliff.git"],
        cwd=other,
        env=bad,
        input=f"refs/heads/skeleton {bad_head} refs/heads/skeleton {'0' * 40}\n",
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0


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


def test_an_indented_by_line_is_rejected(tmp_path):
    """A by-line is a trailer when spaces or a tab sit in front of it."""
    env = _env("Erik Eicke", "ada@example.com")
    env["GITHUB_ACTIONS"] = "true"
    env.pop("AUTHOR_EMAIL", None)

    def commit(directory, body: str) -> subprocess.CompletedProcess[str]:
        directory.mkdir()
        subprocess.check_call(["git", "init"], cwd=directory, env=env)
        (directory / "note.txt").write_text("note\n", encoding="utf-8")
        message = directory / "message.txt"
        message.write_text(body, encoding="utf-8")
        subprocess.check_call(["git", "add", "note.txt"], cwd=directory, env=env)
        subprocess.check_call(["git", "commit", "-F", str(message)], cwd=directory, env=env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--range", "HEAD"],
            cwd=directory,
            env=env,
            text=True,
            capture_output=True,
        )

    spaced = commit(
        tmp_path / "spaced",
        "Add a note\n\n  Signed-off-by: Pat Example <pat@example.com>\n",
    )
    assert spaced.returncode != 0
    tabbed = commit(
        tmp_path / "tabbed",
        "Add a note\n\n\tReviewed-by: Pat Example <pat@example.com>\n",
    )
    assert tabbed.returncode != 0
    hooked = subprocess.run(
        [sys.executable, str(SCRIPT), "--commit-msg", str(tmp_path / "tabbed" / "message.txt")],
        cwd=tmp_path / "tabbed",
        env=env,
        text=True,
        capture_output=True,
    )
    assert hooked.returncode != 0


def test_a_coauthor_line_without_a_blank_line_is_rejected(tmp_path):
    """A line like the blocked merge is a trailer even when git does not parse it."""
    env = _env("Erik Eicke", "ada@example.com")
    env["GITHUB_ACTIONS"] = "true"
    env.pop("AUTHOR_EMAIL", None)
    subprocess.check_call(["git", "init"], cwd=tmp_path, env=env)
    (tmp_path / "note.txt").write_text("note\n", encoding="utf-8")
    message = tmp_path / "message.txt"
    message.write_text(
        "Merge remote-tracking branch 'origin/main' into fixes-1\n"
        "Co-authored-by: Erik Eicke <ada@example.com>\n",
        encoding="utf-8",
    )
    subprocess.check_call(["git", "add", "note.txt"], cwd=tmp_path, env=env)
    subprocess.check_call(["git", "commit", "-F", str(message)], cwd=tmp_path, env=env)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--range", "HEAD"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
