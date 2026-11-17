"""Optional local model. The repository ships no key and no values in the prompt."""

from __future__ import annotations

import os
import shlex
import subprocess

from white_cliff.pipeline import Filing


def model_prompt(filing: Filing) -> str:
    """Describe facts by identifier, role, and unit. Values are not included."""
    lines = [
        "Write prose with {fact:id} and {calc:id} placeholders only.",
        "Do not write digits.",
    ]
    for fact in filing.store.facts():
        if not fact.role:
            continue
        lines.append(f"{fact.id} {fact.role} {fact.unit} {fact.period.kind}")
    return "\n".join(lines) + "\n"


def model_text_from_env(filing: Filing, environ: dict[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    command = env.get("WHITE_CLIFF_MODEL_CMD", "").strip()
    if not command:
        return None
    prompt = model_prompt(filing)
    completed = subprocess.run(
        shlex.split(command),
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout
