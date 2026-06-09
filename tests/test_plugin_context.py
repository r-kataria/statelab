from statelab.core.plugin import Context, Plugin, make_plugin_rng


def test_plugin_default_hooks_are_noops():
    p = Plugin()
    p.setup(lab=None)            # no-op
    assert p.summary() is None   # default


def test_make_plugin_rng_is_deterministic_and_name_scoped():
    r1 = make_plugin_rng(42, "alice")
    r2 = make_plugin_rng(42, "alice")
    r3 = make_plugin_rng(42, "bob")
    seq1 = [r1.random() for _ in range(5)]
    seq2 = [r2.random() for _ in range(5)]
    seq3 = [r3.random() for _ in range(5)]
    assert seq1 == seq2
    assert seq1 != seq3


def test_context_record_and_emit_append_rows():
    rows, events = [], []
    ctx = Context(lab=None, now=12, blocks={"mars": 3}, mined=["mars"],
                  rng=make_plugin_rng(1, "m"), _rows=rows, _events=events)
    ctx.record("price", 100, chain="mars")
    ctx.emit({"kind": "trade", "who": "alice"})
    assert rows == [{"name": "price", "t": 12, "block": 3, "value": 100, "chain": "mars"}]
    assert events == [{"t": 12, "kind": "trade", "who": "alice"}]
