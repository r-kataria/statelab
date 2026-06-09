"""Time control for the harness.

All simulated time is measured in integer multiples of a base unit ``N``
(default: 1 second). ``TimeControl`` is the single source of truth for the
current simulated timestamp; chains, bridges, and actors all consult it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Optional


_UNIT_SUFFIXES = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}


def _parse_base(base: str | int) -> int:
    """Parse a base spec like ``"1s"`` / ``"500ms"`` / ``5`` into integer seconds."""
    if isinstance(base, int):
        if base <= 0:
            raise ValueError("base must be positive")
        return base
    s = base.strip().lower()
    # extract digits then suffix
    i = 0
    while i < len(s) and (s[i].isdigit() or s[i] == "."):
        i += 1
    num = float(s[:i]) if i > 0 else 1.0
    suf = s[i:].strip() or "s"
    if suf == "ms":
        # we don't support sub-second units in this harness; coerce to seconds
        return max(1, int(num / 1000))
    if suf not in _UNIT_SUFFIXES:
        raise ValueError(f"unknown time unit: {suf!r}")
    return max(1, int(num * _UNIT_SUFFIXES[suf]))


@dataclass(frozen=True)
class TimeValue:
    """An immutable duration in base units."""
    units: int

    def __int__(self) -> int:
        return self.units

    def __add__(self, other: "TimeValue | int") -> "TimeValue":
        return TimeValue(self.units + int(other))

    def __sub__(self, other: "TimeValue | int") -> "TimeValue":
        return TimeValue(self.units - int(other))

    def __mul__(self, k: int) -> "TimeValue":
        return TimeValue(self.units * int(k))

    def __lt__(self, other: "TimeValue | int") -> bool:
        return self.units < int(other)

    def __le__(self, other: "TimeValue | int") -> bool:
        return self.units <= int(other)

    def __gt__(self, other: "TimeValue | int") -> bool:
        return self.units > int(other)

    def __ge__(self, other: "TimeValue | int") -> bool:
        return self.units >= int(other)

    def __repr__(self) -> str:
        return f"TimeValue({self.units})"


@dataclass
class Distribution:
    """Pluggable interval distribution. Each draw returns an integer in base units."""
    sampler: Callable[[random.Random], int]
    name: str = "custom"

    def sample(self, rng: random.Random) -> int:
        val = int(self.sampler(rng))
        return max(1, val)


class TimeControl:
    """Authoritative clock for the simulation.

    Parameters
    ----------
    base:
        Base unit, either an integer number of seconds or a string like ``"1s"``.
    fastforward:
        Default multiplier for :meth:`fastforward`.
    """

    def __init__(self, base: str | int = "1s", fastforward: int = 1) -> None:
        self.base_seconds: int = _parse_base(base)
        self._ff: int = max(1, int(fastforward))
        self._now: int = 0  # simulated time in base units, monotonic
        self._frozen: bool = False
        # Hooks the simulator wires up so Time.next() / Time.advance() actually
        # tick chains and the bridge. They are intentionally optional so the
        # module is usable in isolation (e.g. unit tests).
        self._on_advance: list[Callable[[int, int], None]] = []
        self._origin_wall: int = 0  # unix-seconds origin for chain timestamps

    # ---- construction sugar -------------------------------------------------

    def __call__(self, units: int) -> TimeValue:
        """``Time(12)`` -> ``TimeValue(12)``."""
        return TimeValue(int(units))

    # ---- introspection ------------------------------------------------------

    @property
    def now(self) -> int:
        """Current simulated time in base units."""
        return self._now

    @property
    def now_wall(self) -> int:
        """Current simulated time as a unix timestamp (seconds)."""
        return self._origin_wall + self._now * self.base_seconds

    def set_origin(self, wall_seconds: int) -> None:
        """Set the unix-seconds origin used when projecting onto chain timestamps."""
        self._origin_wall = int(wall_seconds)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    # ---- hooks --------------------------------------------------------------

    def on_advance(self, fn: Callable[[int, int], None]) -> None:
        """Register a callback ``fn(prev_units, new_units)`` invoked whenever
        simulated time moves forward."""
        self._on_advance.append(fn)

    # ---- advancement --------------------------------------------------------

    def _advance_by(self, delta_units: int) -> None:
        if delta_units <= 0:
            return
        if self._frozen:
            return
        prev = self._now
        self._now = prev + int(delta_units)
        for cb in list(self._on_advance):
            cb(prev, self._now)

    def next(self) -> int:
        """Advance one base unit. Returns the new ``now``."""
        self._advance_by(1)
        return self._now

    def nextblock(self, chain) -> int:
        """Advance one block-time worth of base units on ``chain``."""
        bt = int(chain.blocktime)
        self._advance_by(bt)
        return self._now

    def advance(self, N: int = 1) -> int:
        """Advance ``N`` base units."""
        self._advance_by(int(N))
        return self._now

    def fastforward(self, multiplier: Optional[int] = None) -> int:
        """Advance ``multiplier * base`` units (default: the value passed at construction)."""
        m = int(multiplier) if multiplier is not None else self._ff
        self._advance_by(m)
        return self._now

    def stop(self) -> None:
        """Freeze simulated time. All advance calls become no-ops until :meth:`resume`."""
        self._frozen = True

    def resume(self) -> None:
        """Unfreeze simulated time."""
        self._frozen = False

    # ---- distributions ------------------------------------------------------

    def constant(self, units: int) -> Distribution:
        return Distribution(lambda rng, u=int(units): u, name=f"const({units})")

    def uniform(self, low: int, high: int) -> Distribution:
        return Distribution(lambda rng, lo=int(low), hi=int(high): rng.randint(lo, hi),
                            name=f"uniform({low},{high})")

    def normal(self, mean: float, var: float, clamp_min: int = 1) -> Distribution:
        std = max(1e-9, float(var)) ** 0.5
        cm = int(clamp_min)

        def _sampler(rng, mu=float(mean), s=std, lo=cm):
            return max(lo, int(round(rng.gauss(mu, s))))

        return Distribution(_sampler, name=f"normal({mean},{var},clamp_min={cm})")

    def exponential(self, mean: float) -> Distribution:
        lam = 1.0 / max(1e-9, float(mean))
        return Distribution(lambda rng, lm=lam: int(round(rng.expovariate(lm))),
                            name=f"exponential({mean})")
