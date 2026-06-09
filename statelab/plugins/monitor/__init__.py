"""Monitor plugin: sample a callable once per block and record it via ctx."""
from __future__ import annotations

from typing import Any, Callable

from ...core.plugin import Plugin


class Monitor(Plugin):
    def __init__(self, name: str, chain, call: Callable[[], Any], every: str = "block"):
        if every not in ("block", "tick"):
            raise ValueError(f"Monitor: every must be 'block' or 'tick', got {every!r}")
        self.name = name
        self.chain = chain
        self.call = call
        self.every = every

    def on_block(self, ctx) -> None:
        # "block" cadence: record only on ticks where this monitor's chain mined.
        # "tick" cadence: record on every on_block call.
        if self.every == "block" and self.chain.name not in ctx.mined:
            return
        try:
            value = self.call()
        except Exception as exc:  # record the error rather than aborting the run
            value = f"<error: {exc!r}>"
        ctx.record(self.name, value, chain=self.chain.name)
