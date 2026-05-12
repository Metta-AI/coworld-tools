from __future__ import annotations

from cogony_policy.cogamer_policy import CogonyPolicy
from tests.conftest import _fake_policy_env_info


def test_cogony_policy_has_recorder_by_default():
    p = CogonyPolicy(_fake_policy_env_info())
    assert p._recorder is not None


def test_cogony_policy_record_dir_kwarg_creates_recorder(tmp_path):
    p = CogonyPolicy(_fake_policy_env_info(), record_dir=str(tmp_path))
    assert p._recorder is not None
    assert p._recorder._record_dir == str(tmp_path)


def test_cogony_policy_log_py_enables_stderr(capsys):
    p = CogonyPolicy(_fake_policy_env_info(), log_py=True)
    p._recorder.emit(type="note", agent=None, stream="py", payload={"text": "hi"})
    assert "[py]" in capsys.readouterr().err


def test_cogony_policy_log_llm_enables_llm_stream(capsys):
    p = CogonyPolicy(_fake_policy_env_info(), log_llm=True)
    p._recorder.emit(type="note", agent=None, stream="llm", payload={"text": "x"})
    assert "[llm]" in capsys.readouterr().err


def test_cogony_policy_log_all_enables_both(capsys):
    p = CogonyPolicy(_fake_policy_env_info(), log="py+llm")
    p._recorder.emit(type="note", agent=None, stream="py", payload={})
    p._recorder.emit(type="note", agent=None, stream="llm", payload={})
    err = capsys.readouterr().err
    assert "[py]" in err and "[llm]" in err


def test_record_dir_writes_events_json_on_episode_end(tmp_path):
    import json

    p = CogonyPolicy(_fake_policy_env_info(), record_dir=str(tmp_path))
    p._recorder.emit(type="note", agent=None, stream="py", payload={"text": "x"})
    p._on_episode_end()
    events_path = tmp_path / "events.json"
    assert events_path.exists()
    data = json.loads(events_path.read_text())
    assert len(data) == 1
    assert data[0]["type"] == "note"


def test_no_record_dir_no_events_json(tmp_path):
    # Without record_dir, no events.json is written even if we call _on_episode_end.
    p = CogonyPolicy(_fake_policy_env_info())
    p._recorder.emit(type="note", agent=None, stream="py", payload={})
    p._on_episode_end()
    assert not (tmp_path / "events.json").exists()


def test_reset_recreates_agent_policies():
    p = CogonyPolicy(_fake_policy_env_info())
    a0_before = p.agent_policy(0)
    p.reset()
    a0_after = p.agent_policy(0)
    assert a0_before is not a0_after


def test_episode_end_is_idempotent(tmp_path):
    import json

    p = CogonyPolicy(_fake_policy_env_info(), record_dir=str(tmp_path))
    p._recorder.emit(type="note", agent=None, stream="py", payload={"text": "a"})
    p._on_episode_end()
    p._on_episode_end()  # second call must be a no-op
    events = json.loads((tmp_path / "events.json").read_text())
    assert len(events) == 1


def test_cogony_policy_without_llm_key_skips_worker(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("COGORA_ANTHROPIC_KEY", raising=False)
    p = CogonyPolicy(_fake_policy_env_info())
    assert p._llm_client is None
    state = p.agent_policy(0)._base_policy.initial_agent_state()
    assert state.worker is None
