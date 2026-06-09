"""Plugin protocol and the per-block Context.

A plugin bundles contracts + bindings + behavior. It implements two hooks:
``setup(lab)`` (run once at start, in registration order) and ``on_block(ctx)``
(run once per block tick). Both are optional; the base class no-ops.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Optional


def make_plugin_rng(seed: int, name: str) -> random.Random:
    """Deterministic per-plugin RNG seeded from ``(seed, name)``."""
    digest = hashlib.sha256(f"{seed}:{name}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


class Plugin:
    """Base class for all plugins. Subclasses override the hooks they need."""

    name: str = "plugin"

    def setup(self, lab: Any) -> None:
        """Deploy contracts, wire peers, fund. Runs at start. Default: no-op."""

    def on_block(self, ctx: "Context") -> None:
        """Per-block behavior. Default: no-op."""

    def summary(self) -> Optional[dict]:
        """Optional contribution to summary.json. Default: nothing."""
        return None


@dataclass
class Context:
    """Handed to ``on_block`` each tick.

    ``mined`` lists the chain names that mined this tick; a monitor records only
    when its chain is in ``mined``. ``record`` adds a monitor sample, ``emit``
    adds an event row, both flowing to the Lab's output writers.
    """
    lab: Any
    now: int
    blocks: dict[str, int]
    mined: list[str]
    rng: random.Random
    _rows: list[dict] = field(default_factory=list)
    _events: list[dict] = field(default_factory=list)

    def record(self, name: str, value: Any, chain: Optional[str] = None) -> None:
        self._rows.append({
            "name": name, "t": self.now,
            "block": self.blocks.get(chain, -1) if chain else -1,
            "value": value, "chain": chain,
        })

    def emit(self, event: dict) -> None:
        row = {"t": self.now}
        row.update(event)
        self._events.append(row)
