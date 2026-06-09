from statelab.core.time import TimeControl, TimeValue


def test_time_call_builds_timevalue():
    t = TimeControl()
    assert int(t(12)) == 12
    assert isinstance(t(12), TimeValue)


def test_advance_is_monotonic_and_fires_hooks():
    t = TimeControl(base="1s")
    seen = []
    t.on_advance(lambda prev, new: seen.append((prev, new)))
    t.advance(5)
    t.advance(3)
    assert t.now == 8
    assert seen == [(0, 5), (5, 8)]


def test_base_parsing_minutes():
    assert TimeControl(base="2m").base_seconds == 120
