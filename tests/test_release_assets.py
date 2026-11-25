"""The release files are the three platform zips, their checksums, and the note."""

from __future__ import annotations

import hashlib
import importlib.util
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
    "WhiteCliff-Mac-Apple-silicon.zip",
    "WhiteCliff-Mac-Intel.zip",
    "WhiteCliff-Windows.zip",
    "SHA256SUMS.txt",
    "how-to-open.md",
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _guide_images() -> list[str]:
    text = (ROOT / "docs" / "how-to-open.md").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\((how-to-[^)]+\.png)\)", text)))


def _zip(path: Path, note: bytes, extra: bytes | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("how-to-open.md", note)
        archive.writestr("how-to-open-de.md", note if extra is None else extra)
        archive.writestr("program.txt", path.name.encode("ascii"))
        if "Windows" in path.name:
            archive.writestr("WhiteCliff-Windows/White Cliff.exe", b"windows-program")
        for picture in _guide_images():
            archive.writestr(picture, picture.encode("ascii"))
        archive.writestr("how-to-de-mac-warning.png", b"de-picture")


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
    assert text.count('pyinstaller==6.22.3') == 3
    assert text.count("retention-days: 90") == 3
    assert text.count("retention-days: 7") == 3
    assert text.count("SHA256SUMS") >= 3
    assert "how-to-open-de.md" not in text
    assert "how-to-open-en.png" in text
    assert "how-to-open-de.png" not in text
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
    english_path = ROOT / "docs" / "how-to-open.md"
    english = english_path.read_text(encoding="utf-8")
    assert "private page" not in english
    assert "a page that runs only on this computer" in english
    steps = _picture_steps(english)
    assert len(steps) >= 8
    for sentence, image in steps:
        name = re.search(r"\(([^)]+)\)", image).group(1)
        path = (english_path.parent / name).resolve()
        assert path.is_file(), name
        note = _png_text(path.read_bytes()).get("Source", "")
        if "Drawing, not a screenshot" in image:
            assert note == "drawing"
        else:
            assert "Screenshot" in image
            assert note == "screenshot"
        assert path.name in download
    assert sum(1 for _sentence, image in steps if "Screenshot" in image) >= 1
    for sentence, _image in steps:
        assert sentence in download
    assert "how-to-open-de.md" not in readme


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
        "WhiteCliff-Mac-Apple-silicon.zip",
        "WhiteCliff-Mac-Intel.zip",
        "WhiteCliff-Windows.zip",
    ):
        assert phrase in docs
    assert "White-Cliff-" not in docs
    assert "White-Cliff-Windows.exe" not in docs
    assert re.search(r"(?m)^1\. ", docs)
    for jargon in ("Gatekeeper", "SmartScreen", "safe", "trusted", "verified"):
        assert jargon not in docs


def test_unreviewed_guides_stay_out_of_the_repo():
    """Open-guide text and pictures for a second language stay out of the public repo."""
    assert not (ROOT / "guides" / "how-to-open-de.md").exists()
    assert not (ROOT / "docs" / "how-to-open-de.md").exists()
    assert not (ROOT / "src" / "white_cliff" / "data" / "how-to-open-de.md").exists()
    pictures = [
        path
        for path in ROOT.rglob("how-to-de-*")
        if ".git" not in path.parts and path.suffix in {".png", ".md"}
    ]
    assert pictures == []
    assert not list(ROOT.rglob("how-to-open-de.png"))
    for path in (
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / "scripts" / "render_guides.py",
        ROOT / "scripts" / "draw_open_guide.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "how-to-open-de" not in text, path.name
        assert "how-to-de-" not in text, path.name


def test_the_assembler_writes_the_release_files_and_does_not_publish(tmp_path: Path):
    source = (ROOT / "scripts" / "assemble_release.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "run" in lowered and "download" in lowered
    for banned in ("gh release", "release create", "git tag", "create_release", "/releases"):
        assert banned not in lowered
    assembler = _load("assemble_release", ROOT / "scripts" / "assemble_release.py")
    note = (ROOT / "docs" / "how-to-open.md").read_bytes()
    extra = b"second-language guide"
    downloaded = tmp_path / "ci"
    for name in ASSETS:
        archive = downloaded / name.replace(".zip", "") / name
        _zip(archive, note, extra)
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
    names = sorted(path.name for path in dest.iterdir())
    assert "how-to-open-de.md" not in names
    assert "how-to-de-mac-warning.png" not in names
    assert names == sorted(list(RELEASE_ASSETS) + images)
    lines = (dest / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split()[-1] for line in lines] == [
        "WhiteCliff-Mac-Apple-silicon.zip",
        "WhiteCliff-Mac-Intel.zip",
        "WhiteCliff-Windows.zip",
        "how-to-open.md",
        *images,
    ]
    for line in lines:
        digest, name = line.split()
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == digest
    assert (dest / "how-to-open.md").read_bytes() == note
    assert (dest / "WhiteCliff-Windows.zip").read_bytes() == (
        downloaded / "WhiteCliff-Windows" / "WhiteCliff-Windows.zip"
    ).read_bytes()
    notes = (ROOT / "docs" / "release-notes.md").read_text(encoding="utf-8")
    bundled = (ROOT / "src" / "white_cliff" / "data" / "release-notes.md").read_text(encoding="utf-8")
    assert notes == bundled
    assert notes.startswith(
        "This tool explains the numbers in a public company filing. "
        "It does not recommend buying, selling or holding any security, "
        "and it is not investment advice."
    )
    assert "\n# White Cliff\n" in notes
    assert "{version}" not in notes
    assert "How it was checked" not in notes
    assert "how-to-open-de" not in notes
    for name in RELEASE_ASSETS:
        if name != "how-to-open.md":
            assert name in notes


def test_release_workflow_cannot_create_or_publish():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert not re.search(r"release:\n\s+types:\s*\[created\]", text)
    assert "workflow_dispatch:" in text
    assert "tag:" in text
    assert "github.event.release.tag_name" not in text
    assert "inputs.tag" in text
    assert text.count("contents: write") == 1
    upload = text.split("\n  upload:", 1)[1]
    assert "contents: write" in upload
    assert "contents: write" not in text.split("\n  upload:", 1)[0]
    assert "isDraft" in text
    assert "--clobber" not in text
    assert "gh run download" in text
    assert "cmp " not in text
    assert "pyinstaller" not in text.lower()
    assert "package-apple-silicon" not in text
    assert "package-intel-mac" not in text
    assert "package-windows" not in text
    assert "missing or expired" in text
    assert "github.token" in text
    assert "secrets." not in text
    assert "smoke_mac.py" not in text
    assert 'gh release view "$RELEASE_TAG" --json isDraft' in text
    assert "gh release upload" in text
    assert "White-Cliff-" not in text
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
    if set(trigger) - {"workflow_dispatch"}:
        problems.append("the workflow has an extra trigger")
    if trigger.get("release") is not None:
        problems.append("the release trigger is not limited to a draft upload")
    dispatch = trigger.get("workflow_dispatch")
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    tag_input = inputs.get("tag") if isinstance(inputs, dict) else None
    if not isinstance(tag_input, dict) or tag_input.get("required") is not True:
        problems.append("workflow_dispatch needs a required tag of the existing release")
    _walk_release(document.get("jobs"), problems)
    expected = "${{ inputs.tag }}"
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
    anchor = '          draft=$(gh release view "$RELEASE_TAG" --json isDraft --jq .isDraft)\n'

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
        "uses: actions/checkout@v4\n",
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
    link = readme.find("https://github.com/EE-Holding/white-cliff/releases/latest")
    assert link > len(readme.split("\n\n", 1)[0])
    assert "docs/how-to-open.md" in readme
    assert "how-to-open-de" not in readme
    assert "Dieses Werkzeug" not in readme
    assert "## What every output carries" in readme
    assert "What the output guarantees" not in readme
    assert "Every figure points back to the filing." in readme
    assert "and nothing else" not in readme
    assert "private page" not in readme
    assert "a page that runs only on this computer" in readme
    for name in (
        "WhiteCliff-Mac-Apple-silicon.zip",
        "WhiteCliff-Mac-Intel.zip",
        "WhiteCliff-Windows.zip",
    ):
        assert name in readme
    for old in (
        "White-Cliff-Mac-Apple-silicon.zip",
        "White-Cliff-Mac-Intel.zip",
        "White-Cliff-Windows.exe",
    ):
        assert old not in readme


def test_how_to_pictures_use_english_and_the_real_file_names():
    source = (ROOT / "scripts" / "draw_open_guide.py").read_text(encoding="utf-8")
    assert "Zeichnung" not in source
    assert "Doppelklick" not in source
    assert all(ord(char) < 128 for char in source)
    for name in (
        "WhiteCliff-Mac-Apple-silicon.zip",
        "WhiteCliff-Mac-Intel.zip",
        "WhiteCliff-Windows.zip",
    ):
        assert name in source
    assert "White-Cliff-" not in source


def test_the_rendered_guide_uses_large_type():
    render = _load("render_guides", ROOT / "scripts" / "render_guides.py")
    page = render.html_page((ROOT / "docs" / "how-to-open.md").read_text(encoding="utf-8"))
    assert "font-size: 32px" in page
    assert "Open Anyway" in page
    assert "![" not in page
    assert "](" not in page
    lists = re.findall(r"<ol>(.*?)</ol>", page, re.S)
    assert [len(re.findall(r"<li>", items)) for items in lists] == [6, 4]
    assert "Unzip the Mac file shown in the picture." in lists[0]
    assert "Double-click the Windows file shown in the picture." in lists[1]
    source = (ROOT / "scripts" / "render_guides.py").read_text(encoding="utf-8")
    assert all(ord(char) < 128 for char in source)
    assert '<html lang="en">' in page
    assert 'lang="de"' not in page


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


def test_public_pages_keep_counts_and_contacts_off_the_page(tmp_path: Path):
    phrase = "and " + "nothing else"
    email = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    public = (
        ROOT / "README.md",
        ROOT / "docs" / "how-to-open.md",
        ROOT / "docs" / "release-notes.md",
        ROOT / "src" / "white_cliff" / "data" / "how-to-open.md",
        ROOT / "src" / "white_cliff" / "data" / "release-notes.md",
        ROOT / "src" / "white_cliff" / "sitebuild.py",
        ROOT / ".github" / "workflows" / "release.yml",
    )
    for path in public:
        text = path.read_text(encoding="utf-8")
        assert phrase not in text, path.name
        assert email.search(text) is None, path.name
        assert "download" + "_count" not in text, path.name
        assert "Mac Apple silicon:" not in text, path.name
    smoke = (ROOT / "scripts" / "smoke_mac.py").read_text(encoding="utf-8")
    assert phrase not in smoke
    from white_cliff.sitebuild import build_site

    output = build_site(tmp_path / "site")
    names = {path.name for path in output.iterdir() if path.is_file()}
    assert "how-to-open-de.md" not in names
    assert not any(name.startswith("how-to-de-") for name in names)


def test_asset_tallies_are_not_anywhere():
    token = "download" + "_count"
    skipped = {".git", ".pytest_cache", "__pycache__", "dist", "build"}
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or skipped.intersection(path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if token in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
