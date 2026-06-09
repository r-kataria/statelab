"""Output writers: events.csv, monitors.csv, summary.json."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def write_outputs(outdir: Path, events: list[dict], rows: list[dict],
                  summary: dict) -> list[str]:
    """Write the three artifacts. Returns the list of error strings (empty if OK)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for frame, fname in ((pd.DataFrame(events), "events.csv"),
                         (pd.DataFrame(rows), "monitors.csv")):
        try:
            frame.to_csv(outdir / fname, index=False)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"{fname}: {exc!r}")
    summary = dict(summary)
    summary["errors"] = list(summary.get("errors", [])) + errors
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return errors
