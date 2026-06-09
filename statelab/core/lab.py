"""Lab: the orchestrator. Owns chains, the plugin registry, the clock, the run
loop, and output writing.

Lifecycle: ``setup`` runs each plugin's ``setup(lab)`` in registration order;
the run loop advances block-by-block, mining due blocks and calling every
plugin's ``on_block(ctx)`` in registration order. Deterministic: same seed ⇒
identical events/monitors/summary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .chain import Chain
from .create2 import Create2Deployer
from .docker import ensure_docker_up
from .output import write_outputs
from .plugin import Context, Plugin, make_plugin_rng
from .time import TimeControl, TimeValue
from .wallet import DEFAULT_MNEMONIC


class Lab:
    def __init__(
        self,
        seed: int = 0,
        duration: TimeValue | int = TimeValue(60),
        outdir: str | Path = "out/lab",
        base: str | int = "1s",
        fastforward: int = 1,
        mnemonic: str = DEFAULT_MNEMONIC,
        wall_origin: int = 1_700_000_000,
        auto_docker: bool = True,
        anvil_ports: list[int] | tuple[int, ...] | None = None,
    ) -> None:
        self.seed = int(seed)
        self.duration = duration if isinstance(duration, TimeValue) else TimeValue(int(duration))
        self.outdir = Path(outdir)
        self.mnemonic = mnemonic
        self.wall_origin = int(wall_origin)
        self.auto_docker = auto_docker
        # PARALLELISM: the Anvil ports this Lab targets. Defaults to the bundled
        # compose pair (8545/8546); a caller can point a Lab at a different
        # port-pair (e.g. 8547/8548) so several independent runs share a machine.
        self.anvil_ports = list(anvil_ports) if anvil_ports else [8545, 8546]

        self.Time = TimeControl(base=base, fastforward=fastforward)
        self.Time.set_origin(self.wall_origin)

        self.chains: list[Chain] = []
        self._chains_by_name: dict[str, Chain] = {}
        self.plugins: list[Plugin] = []
        self._create2 = None

        self._events: list[dict] = []
        self._rows: list[dict] = []
        self._errors: list[str] = []
        self._has_run = False
        self._written = False

    # -- context manager --------------------------------------------------
    def __enter__(self) -> "Lab":
        self.outdir.mkdir(parents=True, exist_ok=True)
        if self.auto_docker:
            ensure_docker_up(self.anvil_ports)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self._errors.append(repr(exc))
        if not self._has_run and exc_type is None:
            self.run()
        elif not self._written:
            self._write()
        return False

    # -- registration -----------------------------------------------------
    def chain(self, name: str, chain_id: int, blocktime: TimeValue,
              rpc_url: Optional[str] = None) -> Chain:
        if int(blocktime) <= 0:
            raise ValueError(
                f"Lab.chain: blocktime must be positive, got {int(blocktime)}"
            )
        c = Chain(name=name, chain_id=chain_id, blocktime=blocktime,
                  rpc_url=rpc_url, mnemonic=self.mnemonic)
        try:
            c.w3.provider.make_request("anvil_reset", [])
        except Exception:
            pass
        try:
            c.set_next_block_timestamp(self.wall_origin)
            c.mine()
        except Exception:
            c.mine()
        self.chains.append(c)
        self._chains_by_name[name] = c
        return c

    def use(self, plugin: Plugin) -> Plugin:
        if any(p.name == plugin.name for p in self.plugins):
            raise ValueError(
                f"Lab.use: a plugin named {plugin.name!r} is already registered; "
                f"give each plugin a unique name"
            )
        self.plugins.append(plugin)
        return plugin

    @property
    def create2(self) -> Create2Deployer:
        """Lazily-built CREATE2 deployer over the registered chains."""
        if getattr(self, "_create2", None) is None:
            self._create2 = Create2Deployer(self.chains)
        return self._create2

    # -- run --------------------------------------------------------------
    def run(self) -> None:
        if self._has_run:
            return
        for plugin in self.plugins:          # setup: registration order
            plugin.setup(self)
        self._loop()
        self._has_run = True
        self._write()

    def _loop(self) -> None:
        end = self.Time.now + int(self.duration)
        next_mine = {c.name: self.Time.now + int(c.blocktime) for c in self.chains}
        rngs = {p.name: make_plugin_rng(self.seed, p.name) for p in self.plugins}
        while self.Time.now < end:
            target = min([end, *next_mine.values()]) if next_mine else end
            target = max(self.Time.now, target)
            if target > self.Time.now:
                self.Time.advance(target - self.Time.now)
            mined: list[str] = []
            for c in self.chains:
                if next_mine[c.name] <= self.Time.now:
                    c.mine(timestamp=self.Time.now_wall)
                    self._events.append({"t": self.Time.now, "kind": "block",
                                         "who": c.name, "number": c.head_number()})
                    next_mine[c.name] = self.Time.now + int(c.blocktime)
                    mined.append(c.name)
            blocks = {c.name: c.head_number() for c in self.chains}
            for plugin in self.plugins:
                ctx = Context(lab=self, now=self.Time.now, blocks=blocks, mined=mined,
                              rng=rngs[plugin.name], _rows=self._rows, _events=self._events)
                try:
                    plugin.on_block(ctx)
                except Exception as exc:
                    self._events.append({"t": self.Time.now, "kind": "plugin_error",
                                         "who": plugin.name, "error": repr(exc)})

    def _write(self) -> None:
        summary = {
            "seed": self.seed,
            "duration": int(self.duration),
            "chains": [c.name for c in self.chains],
            "plugins": [p.name for p in self.plugins],
            "errors": list(self._errors),
        }
        for plugin in self.plugins:
            s = plugin.summary()
            if s:
                summary.setdefault("plugin_summaries", {})[plugin.name] = s
        self._errors += write_outputs(self.outdir, self._events, self._rows, summary)
        self._written = True
