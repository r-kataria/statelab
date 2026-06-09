# `Time` / `TimeControl` / `TimeValue` / `Distribution`

All simulated time is measured in integer multiples of a base unit (one second
by default). `TimeControl` is the authoritative clock; `Time` is a module-level
`TimeControl` used as a convenience constructor.

## `Time`

`Time` is an instance of `TimeControl`, exported from the top level. Calling it
builds a duration:

```python
from statelab import Time

Time(12)        # -> TimeValue(12)
Time(60 * 60)   # one hour, in base units
```

A `Lab` has its own bound clock at `lab.Time`; the module-level `Time` is mainly
for writing durations such as `blocktime=Time(12)` and `delay=Time(24)`.

## `TimeValue`

An immutable duration in base units. `int(TimeValue(12))` is `12`. It supports
`+`, `-`, `*`, and ordering against other `TimeValue`s and plain ints, so
durations compose: `Time(12) + Time(3)`, `Time(12) * 5`.

## `TimeControl`

The clock. A `Lab` constructs and drives one; you rarely instantiate it
directly.

```python
TimeControl(base="1s", fastforward=1)
```

- `now` - current simulated time in base units.
- `now_wall` - current time as a unix timestamp (the origin plus `now * base`).
- `set_origin(wall_seconds)` - set the unix origin for chain timestamps.
- `advance(N=1)` / `next()` / `nextblock(chain)` / `fastforward(multiplier=None)`
  move time forward by `N` units, one unit, one chain's block time, or the
  fast-forward multiplier.
- `stop()` / `resume()` - freeze and unfreeze; while frozen, advances are no-ops.
- `is_frozen` - whether the clock is frozen.
- `on_advance(fn)` - register a callback `fn(prev, new)` run on each advance.

## `Distribution`

A pluggable interval sampler; each draw returns an integer of at least one base
unit. Build one from a `TimeControl`'s factory methods:

```python
d = lab.Time.uniform(5, 15)      # uniform integer interval in [5, 15]
n = d.sample(rng)                # draw with a random.Random
```

Factories: `constant(units)`, `uniform(low, high)`,
`normal(mean, var, clamp_min=1)`, `exponential(mean)`.
