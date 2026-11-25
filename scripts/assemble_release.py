#!/usr/bin/env python3
"""Copy one CI run's files into a local folder.

The folder holds the files a release would carry. The script downloads that
run and writes the folder on this computer. It does not create a tag and it
does not send the folder anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

CI_ZIPS = (
    "WhiteCliff-Mac-Apple-silicon.zip",
    "WhiteCliff-Mac-Intel.zip",
    "WhiteCliff-Windows.zip",
)


class AssembleError(Exception):
    """The folder could not be assembled."""


def _find(downloaded: Path, name: str) -> Path:
    matches = [path for path in downloaded.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise AssembleError(f"{name} was not in the CI run")
    return matches[0]


def _check(archive: Path) -> str:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = archive.parent / "SHA256SUMS"
    if not sidecar.is_file():
        return digest
    expected = ""
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == archive.name:
            expected = parts[0]
    if expected and expected != digest:
        raise AssembleError(f"{archive.name} does not match SHA256SUMS")
    return digest


def _named(archive: Path, filename: str) -> bytes:
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            if Path(name).name == filename:
                return zipped.read(name)
    raise AssembleError(f"{filename} was not in the zip")


def assemble(downloaded: Path, dest: Path, *, version: str, date: str, template: Path) -> None:
    if not version.strip() or not date.strip():
        raise AssembleError("the version and the date are empty")
    if dest.exists() and any(dest.iterdir()):
        raise AssembleError("the output folder is not empty")
    checked = [_find(downloaded, name) for name in CI_ZIPS]
    for archive in checked:
        _check(archive)
    if not template.is_file():
        raise AssembleError("the notes file is missing")
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    first = checked[0]
    for archive in checked:
        target = dest / archive.name
        target.write_bytes(archive.read_bytes())
        written.append(target)
    note = dest / "how-to-open.md"
    note.write_bytes(_named(first, "how-to-open.md"))
    written.append(note)
    with zipfile.ZipFile(first) as zipped:
        pictures = sorted(
            name
            for name in zipped.namelist()
            if Path(name).name.startswith("how-to-")
            and Path(name).name.endswith(".png")
            and not Path(name).name.startswith("how-to-de-")
        )
        if not pictures:
            raise AssembleError("the open guide pictures were not in the zip")
        seen: set[str] = set()
        for name in pictures:
            filename = Path(name).name
            if filename in seen:
                continue
            seen.add(filename)
            target = dest / filename
            target.write_bytes(zipped.read(name))
            written.append(target)
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in written
    ]
    (dest / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def download_run(run_id: str, dest: Path) -> None:
    if not run_id.isdigit():
        raise AssembleError("the run id is not a number")
    subprocess.run(
        ["gh", "run", "download", run_id, "--dir", str(dest)],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble a local folder from a CI run.")
    parser.add_argument("run_id")
    parser.add_argument("dest", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    template = Path(__file__).resolve().parents[1] / "docs" / "release-notes.md"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = Path(tmp)
            download_run(args.run_id, downloaded)
            assemble(
                downloaded,
                args.dest,
                version=args.version,
                date=args.date,
                template=template,
            )
    except AssembleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
