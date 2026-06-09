"""Load precompiled Foundry artifacts (ABI + bytecode).

Artifacts live at ``<root>/artifacts/<File.sol>/<ContractName>.json``. The root
is resolved from either an installed package (``package=``, via
``importlib.resources``) or a filesystem directory (``path=``). Artifacts are
shipped as package data; ``forge`` is only used in dev to regenerate them
(see ``regenerate_artifacts`` below), never at runtime.
"""
from __future__ import annotations

import json
import subprocess
from importlib import resources
from pathlib import Path
from typing import Optional


def load_artifact(
    sol_file: str,
    contract_name: str,
    *,
    package: Optional[str] = None,
    path: Optional[str | Path] = None,
) -> dict:
    """Return the parsed artifact dict (``{"abi": [...], "bytecode": ...}``).

    Exactly one of ``package`` or ``path`` must be given.
    """
    if (package is None) == (path is None):
        raise ValueError("load_artifact: pass exactly one of package= or path=")
    rel = f"artifacts/{sol_file}/{contract_name}.json"
    if package is not None:
        root = resources.files(package)
        text = (root / rel).read_text()
    else:
        text = (Path(path) / rel).read_text()
    return json.loads(text)


def regenerate_artifacts(project_dir: str | Path) -> None:
    """Dev-only: run ``forge build`` in ``project_dir`` to refresh artifacts.

    Not called at runtime. Requires Foundry on PATH.
    """
    res = subprocess.run(
        ["forge", "build"], cwd=str(project_dir),
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            "forge build failed:\nSTDOUT:\n" + res.stdout + "\nSTDERR:\n" + res.stderr
        )
