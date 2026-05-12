from cvc_policy.recorder import EventRecorder, fmt


def test_emit_appends_event_with_step_and_stream():
    rec = EventRecorder()
    rec.set_step(7)
    rec.emit(type="action", agent=0, stream="py", payload={"role": "miner"})
    assert rec.events == [
        {
            "step": 7,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner"},
        }
    ]


def test_emit_without_step_defaults_to_zero():
    rec = EventRecorder()
    rec.emit(type="note", agent=None, stream="py", payload={"text": "hi"})
    assert rec.events[0]["step"] == 0


def test_fmt_action_event():
    ev = {
        "step": 3,
        "agent": 0,
        "stream": "py",
        "type": "action",
        "payload": {"role": "miner", "summary": "mine_carbon"},
    }
    assert fmt(ev) == "[py] a0 step=3 action mine_carbon"


def test_fmt_team_event_has_no_agent_prefix():
    ev = {
        "step": 10,
        "agent": None,
        "stream": "py",
        "type": "note",
        "payload": {"text": "season changed"},
    }
    assert fmt(ev) == "[py] step=10 note text='season changed'"


def test_fmt_patch_applied_shows_applied_fields():
    ev = {
        "step": 500,
        "agent": 2,
        "stream": "llm",
        "type": "patch_applied",
        "payload": {
            "applied": {"resource_bias": "carbon"},
            "rationale": "low supply",
        },
    }
    s = fmt(ev)
    assert s.startswith("[llm] a2 step=500 patch_applied")
    assert "resource_bias=carbon" in s


def test_stderr_sink_filters_by_stream(capsys):
    rec = EventRecorder(stderr_streams={"py"})
    rec.emit(type="action", agent=0, stream="py", payload={"role": "miner"})
    rec.emit(type="llm_tool_call", agent=0, stream="llm", payload={"tool": "patch"})
    err = capsys.readouterr().err.splitlines()
    assert any(line.startswith("[py]") for line in err)
    assert not any(line.startswith("[llm]") for line in err)


def test_flush_to_json(tmp_path):
    import json

    rec = EventRecorder()
    rec.emit(type="action", agent=0, stream="py", payload={})
    rec.flush_json(tmp_path / "events.json")
    data = json.loads((tmp_path / "events.json").read_text())
    assert len(data) == 1
    assert data[0]["type"] == "action"


def test_per_step_drain_returns_events_for_current_step():
    rec = EventRecorder()
    rec.set_step(5)
    rec.emit(type="action", agent=0, stream="py", payload={})
    rec.emit(type="role_change", agent=1, stream="py", payload={})
    rec.set_step(6)
    rec.emit(type="action", agent=0, stream="py", payload={})
    events_at_5 = rec.events_for_step(5)
    assert len(events_at_5) == 2


def test_events_for_step_with_agent_filter():
    rec = EventRecorder()
    rec.set_step(3)
    rec.emit(type="action", agent=0, stream="py", payload={})
    rec.emit(type="action", agent=1, stream="py", payload={})
    assert len(rec.events_for_step(3, agent=0)) == 1
    assert rec.events_for_step(3, agent=0)[0]["agent"] == 0


def test_events_for_step_is_O1_after_many_emits():
    rec = EventRecorder()
    for s in range(500):
        rec.set_step(s)
        for a in range(8):
            rec.emit(type="action", agent=a, stream="py", payload={})
    import time
    t0 = time.perf_counter()
    for s in range(500):
        _ = rec.events_for_step(s)
    assert time.perf_counter() - t0 < 0.05


def test_events_for_step_returns_correct_events_and_is_stable():
    rec = EventRecorder()
    rec.set_step(1)
    rec.emit(type="action", agent=0, stream="py", payload={"s": 1})
    rec.set_step(2)
    rec.emit(type="action", agent=0, stream="py", payload={"s": 2})
    snapshot_at_1 = list(rec.events_for_step(1))
    rec.set_step(3)
    rec.emit(type="action", agent=0, stream="py", payload={"s": 3})
    # later emits at other steps don't change earlier-step results
    assert rec.events_for_step(1) == snapshot_at_1
    assert len(rec.events_for_step(1)) == 1
    assert rec.events_for_step(1)[0]["payload"] == {"s": 1}
    assert len(rec.events_for_step(2)) == 1
    assert len(rec.events_for_step(3)) == 1
