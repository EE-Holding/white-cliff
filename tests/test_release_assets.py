"""The release files are the three platform zips, their checksums, and the note."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = (
    "WhiteCliff-Mac-Apple-silicon.zip",
    "WhiteCliff-Mac-Intel.zip",
    "WhiteCliff-Windows.zip",
)
RELEASE_ASSETS = (
    "White-Cliff-Mac-Apple-silicon.zip",
    "White-Cliff-Mac-Intel.zip",
    "White-Cliff-Windows.exe",
    "SHA256SUMS.txt",
    "how-to-open.md",
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip(path: Path, note: bytes, german: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("how-to-open.md", note)
        archive.writestr("how-to-open-de.md", note if german is None else german)
        archive.writestr("program.txt", path.name.encode("ascii"))
        if "Windows" in path.name:
            archive.writestr("WhiteCliff-Windows/White Cliff.exe", b"windows-program")


def test_the_five_jobs_publish_plain_names_and_checksums():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = re.findall(r"\n  ([a-z0-9-]+):\n", text.split("jobs:", 1)[1])
    assert jobs == [
        "test",
        "authorship",
        "package-apple-silicon",
        "package-intel-mac",
        "package-windows",
    ]
    for name in ASSETS:
        assert name in text
    assert text.count("SHA256SUMS") >= 3
    assert text.count("how-to-open-de.md") >= 3
    assert "how-to-open-en.png" in text
    assert "how-to-open-de.png" in text
    lowered = text.lower()
    for banned in ("codesign", "notarize", "notarytool", "productsign", "signtool"):
        assert banned not in lowered


def test_the_note_names_the_files_and_the_warning_buttons():
    docs = (ROOT / "docs" / "how-to-open.md").read_text(encoding="utf-8")
    bundled = (ROOT / "src" / "white_cliff" / "data" / "how-to-open.md").read_text(encoding="utf-8")
    assert docs == bundled
    for phrase in (
        "Move to Trash",
        "Open Anyway",
        "More info",
        "Run anyway",
        "not signed",
        "Right-click",
        "Privacy & Security",
        "open source",
        "SHA256SUMS.txt",
        "White-Cliff-Mac-Apple-silicon.zip",
        "White-Cliff-Mac-Intel.zip",
        "White-Cliff-Windows.exe",
    ):
        assert phrase in docs
    for old in ASSETS:
        assert old not in docs
    assert re.search(r"(?m)^1\. ", docs)
    for jargon in ("Gatekeeper", "SmartScreen", "safe", "trusted"):
        assert jargon not in docs


def test_the_german_guide_needs_native_review_and_is_not_certified():
    docs = (ROOT / "docs" / "how-to-open-de.md").read_text(encoding="utf-8")
    bundled = (ROOT / "src" / "white_cliff" / "data" / "how-to-open-de.md").read_text(encoding="utf-8")
    assert docs == bundled
    assert docs.startswith(
        "This tool explains the numbers in a public company filing. "
        "It does not recommend buying, selling or holding any security, "
        "and it is not investment advice."
    )
    assert "needs a native review" in docs
    assert "not a certified translation" in docs
    assert "is a certified translation" not in docs
    assert "Muttersprache" in docs
    assert "keine geprüfte Übersetzung" in docs
    for phrase in (
        "rechten Maustaste",
        "Systemeinstellungen",
        "Datenschutz & Sicherheit",
        "Dennoch öffnen",
        "Weitere Informationen",
        "Trotzdem ausführen",
        "nicht signiert",
        "quelloffen",
        "SHA256SUMS.txt",
        "White-Cliff-Mac-Apple-silicon.zip",
        "White-Cliff-Mac-Intel.zip",
        "White-Cliff-Windows.exe",
    ):
        assert phrase in docs
    for old in ASSETS:
        assert old not in docs
    assert re.search(r"(?m)^1\. ", docs)


def test_the_assembler_writes_the_release_files_and_does_not_publish(tmp_path: Path):
    source = (ROOT / "scripts" / "assemble_release.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "run" in lowered and "download" in lowered
    for banned in ("gh release", "release create", "git tag", "create_release", "/releases"):
        assert banned not in lowered
    assembler = _load("assemble_release", ROOT / "scripts" / "assemble_release.py")
    note = (ROOT / "docs" / "how-to-open.md").read_bytes()
    german = (ROOT / "docs" / "how-to-open-de.md").read_bytes()
    downloaded = tmp_path / "ci"
    for name in ASSETS:
        archive = downloaded / name.replace(".zip", "") / name
        _zip(archive, note, german)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (archive.parent / "SHA256SUMS").write_text(f"{digest}  {name}\n", encoding="utf-8")
    dest = tmp_path / "release"
    assembler.assemble(
        downloaded,
        dest,
        version="1",
        date="23 November 2026",
        template=ROOT / "docs" / "release-notes.md",
    )
    assert tuple(sorted(path.name for path in dest.iterdir())) == tuple(sorted(RELEASE_ASSETS))
    lines = (dest / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split()[-1] for line in lines] == [
        "White-Cliff-Mac-Apple-silicon.zip",
        "White-Cliff-Mac-Intel.zip",
        "White-Cliff-Windows.exe",
        "how-to-open.md",
    ]
    for line in lines:
        digest, name = line.split()
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == digest
    assert (dest / "how-to-open.md").read_bytes() == note
    assert (dest / "White-Cliff-Windows.exe").read_bytes() == b"windows-program"
    notes = (ROOT / "docs" / "release-notes.md").read_text(encoding="utf-8")
    assert notes.startswith(
        "This tool explains the numbers in a public company filing. "
        "It does not recommend buying, selling or holding any security, "
        "and it is not investment advice."
    )
    for name in RELEASE_ASSETS:
        if name != "how-to-open.md":
            assert name in notes
    assert "needs a native review" in notes
    assert "not a certified translation" in notes


def test_release_workflow_cannot_create_or_publish():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert re.search(r"release:\n\s+types:\s*\[created\]", text)
    assert "workflow_dispatch:" in text
    assert "tag:" in text
    assert "github.event.release.tag_name || inputs.tag" in text
    assert "contents: write" in text
    assert "github.token" in text
    assert "secrets." not in text
    assert text.count('python3 scripts/smoke_mac.py "dist/White Cliff.app/Contents/MacOS/White Cliff"') == 2
    assert "gh release view" in text
    assert "gh release upload" in text
    for name in RELEASE_ASSETS:
        assert name in text
    lowered = text.lower()
    for banned in (
        "gh release create",
        "release create",
        "git tag",
        "create_release",
        "create-release",
        "action-gh-release",
        "gh release edit",
        "draft: false",
        "--draft",
        "softprops",
        "codesign",
        "notarize",
        "notarytool",
        "productsign",
        "signtool",
    ):
        assert banned not in lowered


def test_the_readme_puts_download_ahead_of_the_developer_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(
        "This tool explains the numbers in a public company filing. "
        "It does not recommend buying, selling or holding any security, "
        "and it is not investment advice."
    )
    download = readme.find("## Download")
    developers = readme.find("## For developers")
    install = readme.find("pip install")
    command = readme.find("white-cliff explain pinned")
    assert 0 < download < developers < install < command
    assert developers < install
    assert developers < command
    assert "https://github.com/EE-Holding/white-cliff/releases/latest" in readme
    assert "docs/how-to-open.md" in readme
    assert "Dieses Werkzeug" not in readme


def test_the_rendered_guide_uses_large_type():
    render = _load("render_guides", ROOT / "scripts" / "render_guides.py")
    page = render.html_page((ROOT / "docs" / "how-to-open.md").read_text(encoding="utf-8"))
    german = render.html_page((ROOT / "docs" / "how-to-open-de.md").read_text(encoding="utf-8"))
    assert "font-size: 32px" in page
    assert "Open Anyway" in page
    assert "needs a native review" in german
    assert 'class="review"' in german


def test_a_checksum_mismatch_is_not_assembled(tmp_path: Path):
    assembler = _load("assemble_release", ROOT / "scripts" / "assemble_release.py")
    downloaded = tmp_path / "ci"
    for name in ASSETS:
        archive = downloaded / name.replace(".zip", "") / name
        _zip(archive, b"note")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if name == "WhiteCliff-Windows.zip":
            digest = "0" * 64
        (archive.parent / "SHA256SUMS").write_text(f"{digest}  {name}\n", encoding="utf-8")
    try:
        assembler.assemble(
            downloaded,
            tmp_path / "release",
            version="1",
            date="23 November 2026",
            template=ROOT / "docs" / "release-notes.md",
        )
    except assembler.AssembleError as exc:
        assert "WhiteCliff-Windows.zip" in str(exc)
    else:
        raise AssertionError("a wrong checksum was accepted")


def test_download_counts_sum_each_platform_and_keep_the_token(tmp_path, monkeypatch, capsys):
    source = (ROOT / "scripts" / "download_counts.py").read_text(encoding="utf-8")
    assert "download_count" in source
    lowered = source.lower()
    for banned in ("gh release", "release create", "post", "uploads.github"):
        assert banned not in lowered
    counts = _load("download_counts", ROOT / "scripts" / "download_counts.py")
    token = "token-value-for-the-test"
    monkeypatch.setenv("GITHUB_TOKEN", token)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)

    def opener(request, timeout=30):
        assert request.data is None
        assert request.get_header("Authorization") == "Bearer " + token
        assert request.full_url.startswith("https://api.github.com/repos/EE-Holding/white-cliff/releases")

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Response(
            b'[{"assets":['
            b'{"name":"WhiteCliff-Mac-Apple-silicon.zip","download_count":4},'
            b'{"name":"WhiteCliff-Mac-Intel.zip","download_count":2},'
            b'{"name":"WhiteCliff-Windows.zip","download_count":7},'
            b'{"name":"how-to-open.md","download_count":9}'
            b"]}]"
        )

    monkeypatch.setattr(counts.urllib.request, "urlopen", opener)
    assert counts.main() == 0
    out = capsys.readouterr().out
    assert "Mac Apple silicon: 4" in out
    assert "Mac Intel: 2" in out
    assert "Windows: 7" in out
    assert token not in out
    assert "9" not in out
    written = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert written == []
