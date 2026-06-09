import json
from pathlib import Path

from statelab.core.output import write_outputs


def test_write_outputs_creates_three_files(tmp_path: Path):
    events = [{"t": 0, "kind": "block", "who": "mars"}]
    rows = [{"name": "price", "t": 0, "block": 1, "value": 100, "chain": "mars"}]
    summary = {"seed": 7, "duration": 60, "plugins": ["m"]}
    write_outputs(tmp_path, events, rows, summary)
    assert (tmp_path / "events.csv").exists()
    assert (tmp_path / "monitors.csv").exists()
    loaded = json.loads((tmp_path / "summary.json").read_text())
    assert loaded["seed"] == 7 and loaded["plugins"] == ["m"]
