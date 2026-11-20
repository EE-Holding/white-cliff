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


def _guide_images() -> list[str]:
    names: set[str] = set()
    for guide in ("how-to-open.md", "how-to-open-de.md"):
        text = (ROOT / "docs" / guide).read_text(encoding="utf-8")
        names.update(re.findall(r"\((how-to-[^)]+\.png)\)", text))
    return sorted(names)


def _zip(path: Path, note: bytes, german: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("how-to-open.md", note)
        archive.writestr("how-to-open-de.md", note if german is None else german)
        archive.writestr("program.txt", path.name.encode("ascii"))
        if "Windows" in path.name:
            archive.writestr("WhiteCliff-Windows/White Cliff.exe", b"windows-program")
        for picture in _guide_images():
            archive.writestr(picture, picture.encode("ascii"))


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


def _png_text(data: bytes) -> dict[str, str]:
    found: dict[str, str] = {}
    position = 8
    while position + 8 <= len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        chunk = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"tEXt" and b"\x00" in chunk:
            key, value = chunk.split(b"\x00", 1)
            found[key.decode("latin-1")] = value.decode("latin-1")
        if kind == b"IEND":
            break
    return found


def _picture_steps(text: str) -> list[tuple[str, str]]:
    steps: list[tuple[str, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if re.match(r"^\d+\. .+\.$", lines[index]):
            sentence = lines[index]
            assert sentence.split(". ", 1)[1].count(".") == 1
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            assert lines[index].startswith("!["), sentence
            steps.append((sentence, lines[index]))
        index += 1
    return steps


def test_each_open_step_has_one_picture():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    download = readme.split("## Download", 1)[1].split("## For developers", 1)[0]
    english = (ROOT / "docs" / "how-to-open.md").read_text(encoding="utf-8")
    german = (ROOT / "docs" / "how-to-open-de.md").read_text(encoding="utf-8")
    for text, drawing_mark, shot_mark in (
        (english, "Drawing, not a screenshot", "Screenshot"),
        (german, "Zeichnung, keine Bildschirmaufnahme", "Bildschirmaufnahme"),
    ):
        steps = _picture_steps(text)
        assert len(steps) >= 8
        for sentence, image in steps:
            name = re.search(r"\(([^)]+)\)", image).group(1)
            path = ROOT / "docs" / name
            assert path.is_file(), name
            note = _png_text(path.read_bytes()).get("Source", "")
            if drawing_mark in image:
                assert note == "drawing"
            else:
                assert shot_mark in image
                assert note == "screenshot"
            assert name in download or Path(name).name in download
        assert sum(1 for _sentence, image in steps if shot_mark in image and drawing_mark not in image) >= 1
    for sentence, _image in _picture_steps(english):
        assert sentence in download


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
    images = _guide_images()
    assert sorted(path.name for path in dest.iterdir()) == sorted(
        list(RELEASE_ASSETS) + ["how-to-open-de.md", *images]
    )
    lines = (dest / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split()[-1] for line in lines] == [
        "White-Cliff-Mac-Apple-silicon.zip",
        "White-Cliff-Mac-Intel.zip",
        "White-Cliff-Windows.exe",
        "how-to-open.md",
        "how-to-open-de.md",
        *images,
    ]
    for line in lines:
        digest, name = line.split()
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == digest
    assert (dest / "how-to-open.md").read_bytes() == note
    assert (dest / "how-to-open-de.md").read_bytes() == german
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


def _release_on(doc: dict):
    if "on" in doc:
        return doc["on"]
    return doc.get(True)


def _scan_release_line(line: str) -> list[str]:
    lowered = line.strip().lower()
    found: list[str] = []
    if re.search(r"\bgh\s+release\s+create\b", lowered):
        found.append("gh release create")
    if re.search(r"\bgh\s+release\s+edit\b", lowered):
        found.append("gh release edit")
    if "createrelease" in lowered:
        found.append("createRelease")
    if "updaterelease" in lowered:
        found.append("updateRelease")
    if re.search(r"\bgit\s+tag\b", lowered):
        found.append("git tag")
    if re.search(r"\bgit\s+push\b", lowered) and "--tags" in lowered:
        found.append("git push --tags")
    if (
        "draft: false" in lowered
        or "draft:false" in lowered
        or "--draft=false" in lowered
        or "--draft false" in lowered
    ):
        found.append("draft: false")
    creates = re.search(r"(?:-x|--method)\s+post\b", lowered) and re.search(
        r"/releases(?:[?'\"\s]|$)", lowered
    )
    if creates and "/assets" not in lowered:
        found.append("createRelease API")
    if re.search(r"(?:-x|--method)\s+patch\b", lowered) and "/releases" in lowered:
        found.append("updateRelease API")
    if re.search(r"\bgh\s+release\b", lowered) and re.search(r"--(?:notes|notes-file|body)\b", lowered):
        found.append("gh release edit")
    return found


def _walk_release(node, problems: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() == "draft" and (value is False or str(value).strip().lower() == "false"):
                problems.append("draft: false")
            if str(key).lower() == "uses" and isinstance(value, str):
                lowered = value.lower()
                for marker in (
                    "action-gh-release",
                    "create-release",
                    "release-action",
                    "automatic-releases",
                    "goreleaser-action",
                ):
                    if marker in lowered:
                        problems.append(f"release-creating action {value}")
            _walk_release(value, problems)
        return
    if isinstance(node, list):
        for item in node:
            _walk_release(item, problems)
        return
    if isinstance(node, str):
        for line in node.splitlines():
            problems.extend(_scan_release_line(line))


def release_workflow_problems(text: str) -> list[str]:
    """Return the ways a workflow could create, publish, or edit a release."""
    import yaml

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [f"release.yml is not valid YAML: {exc}"]
    if not isinstance(document, dict):
        return ["release.yml is not a workflow"]
    problems: list[str] = []
    trigger = _release_on(document)
    if not isinstance(trigger, dict):
        problems.append("the workflow has no release trigger")
        trigger = {}
    if set(trigger) - {"release", "workflow_dispatch"}:
        problems.append("the workflow has an extra trigger")
    release = trigger.get("release")
    types = release.get("types") if isinstance(release, dict) else None
    if types != ["created"]:
        problems.append("the release trigger is not limited to created")
    dispatch = trigger.get("workflow_dispatch")
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    tag_input = inputs.get("tag") if isinstance(inputs, dict) else None
    if not isinstance(tag_input, dict) or tag_input.get("required") is not True:
        problems.append("workflow_dispatch needs a required tag of the existing release")
    _walk_release(document.get("jobs"), problems)
    expected = "${{ github.event.release.tag_name || inputs.tag }}"
    found = []
    jobs = document.get("jobs") if isinstance(document.get("jobs"), dict) else {}
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str) and re.search(r"\bgh\s+release\s+upload\b", run):
                found.append((job, step, run))
    if len(found) != 1:
        problems.append("the upload step must target the existing release only")
        return problems
    job, step, run = found[0]
    env: dict = {}
    if isinstance(job.get("env"), dict):
        env.update(job["env"])
    if isinstance(step.get("env"), dict):
        env.update(step["env"])
    tag = env.get("RELEASE_TAG", "")
    same = isinstance(tag, str) and re.sub(r"\s+", "", tag) == re.sub(r"\s+", "", expected)
    aimed = bool(re.search(r'gh\s+release\s+upload\s+"\$RELEASE_TAG"', run)) and same
    inlined = re.sub(r"\s+", "", expected) in re.sub(r"\s+", "", run)
    if not aimed and not inlined:
        problems.append("the upload step must target the existing release only")
    if not re.search(r'gh\s+release\s+view\s+"\$RELEASE_TAG"', run):
        problems.append("the upload step must target the existing release only")
    return problems


def test_release_yml_only_uploads_to_an_existing_release():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert release_workflow_problems(text) == []
    anchor = '          gh release view "$RELEASE_TAG" --json tagName > /dev/null\n'

    def inserted(command: str) -> str:
        return f"          {command}\n{anchor}"

    forbidden = {
        "gh release create": inserted('gh release create "$RELEASE_TAG"'),
        "gh release edit": inserted('gh release edit "$RELEASE_TAG" --notes "pasted"'),
        "createRelease": inserted("gh api graphql -f query='mutation { createRelease(input: {}) { id } }'"),
        "updateRelease": inserted("gh api graphql -f query='mutation { updateRelease(input: {}) { id } }'"),
        "git tag": inserted("git tag v1"),
        "git push --tags": inserted("git push --tags"),
        "draft: false": inserted("echo 'draft: false'"),
        "create release api": inserted("gh api --method POST /repos/EE-Holding/white-cliff/releases"),
        "update release api": inserted(
            "gh api --method PATCH /repos/EE-Holding/white-cliff/releases/1 -f body=hello"
        ),
    }
    for label, snippet in forbidden.items():
        problems = release_workflow_problems(text.replace(anchor, snippet, 1))
        assert problems, label
        assert any(label.split()[0].lower() in problem.lower() for problem in problems)
    action = text.replace(
        "uses: actions/upload-artifact@v4\n",
        "uses: softprops/action-gh-release@v2\n",
        1,
    )
    assert release_workflow_problems(action)
    other_tag = text.replace(
        'gh release upload "$RELEASE_TAG" \\',
        'gh release upload "v9" \\',
        1,
    )
    assert release_workflow_problems(other_tag)


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
