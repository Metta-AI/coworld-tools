from __future__ import annotations

from players.player_sdk import TraceConfig, TraceEvent

SAMPLE_GROUPS = {
    "action": ("act_*", "domain.move"),
    "state": ("domain.phase_*",),
}


def event(name: str) -> TraceEvent:
    return TraceEvent(tick=0, name=name, data={})


def config(
    env: dict[str, str],
    *,
    default_filter=None,
    low_volume_events: frozenset[str] = frozenset(),
    noisy_events: frozenset[str] = frozenset(),
) -> TraceConfig:
    return TraceConfig.from_env(
        env_prefix="TESTGAME",
        groups=SAMPLE_GROUPS,
        default_filter=default_filter,
        low_volume_events=low_volume_events,
        noisy_events=noisy_events,
        env=env,
    )


def test_group_matching_allows_selected_group_events() -> None:
    trace_config = config({"TESTGAME_TRACE_GROUPS": "action"})

    assert trace_config.has_targets
    assert trace_config.allows(event("act_wait"))
    assert trace_config.allows(event("DOMAIN.MOVE"))
    assert not trace_config.allows(event("domain.phase_start"))


def test_include_patterns_allow_matching_events_only_when_targets_present() -> None:
    trace_config = config({"TESTGAME_TRACE_INCLUDE": "domain.phase_start"})

    assert trace_config.allows(event("domain.phase_start"))
    assert not trace_config.allows(event("domain.phase_end"))


def test_exclude_patterns_reject_even_when_event_matches_target() -> None:
    trace_config = config(
        {
            "TESTGAME_TRACE_GROUPS": "action",
            "TESTGAME_TRACE_EXCLUDE": "act_wait",
        }
    )

    assert trace_config.excludes_event("ACT_WAIT")
    assert not trace_config.allows(event("act_wait"))


def test_domain_prefix_expansion_for_include_and_exclude_patterns() -> None:
    included = config({"TESTGAME_TRACE_INCLUDE": "move"})
    excluded = config(
        {
            "TESTGAME_TRACE_GROUPS": "action",
            "TESTGAME_TRACE_EXCLUDE": "move",
        }
    )

    assert included.targets_event("domain.move")
    assert included.allows(event("domain.move"))
    assert excluded.excludes_event("domain.move")
    assert not excluded.allows(event("domain.move"))


def test_debug_and_viewer_levels_allow_all_events() -> None:
    for level in ("debug", "viewer"):
        trace_config = config({"TESTGAME_TRACE": level})

        assert trace_config.allows(event("framework_noise"))
        assert trace_config.allows(event("domain.noisy"))


def test_default_filter_governs_when_no_targets_or_special_level() -> None:
    permissive = config({}, default_filter=lambda trace_event: trace_event.name.startswith("domain."))
    restrictive = config({}, default_filter=lambda trace_event: trace_event.name == "domain.keep")

    assert permissive.allows(event("domain.anything"))
    assert not permissive.allows(event("framework_noise"))
    assert restrictive.allows(event("domain.keep"))
    assert not restrictive.allows(event("domain.drop"))


def test_missing_default_filter_allows_all_when_no_targets_or_special_level() -> None:
    trace_config = config({})

    assert trace_config.allows(event("framework_noise"))
    assert trace_config.allows(event("domain.noisy"))


def test_lean_group_uses_low_volume_and_noisy_event_sets() -> None:
    trace_config = config(
        {"TESTGAME_TRACE_GROUPS": "lean"},
        low_volume_events=frozenset({"framework.low"}),
        noisy_events=frozenset({"domain.noisy"}),
    )

    assert trace_config.allows(event("framework.low"))
    assert trace_config.allows(event("domain.significant"))
    assert not trace_config.allows(event("domain.noisy"))
    assert not trace_config.allows(event("framework.other"))


def test_from_env_uses_prefix_derived_variable_names() -> None:
    trace_config = config(
        {
            "OTHER_TRACE": "debug",
            "OTHER_TRACE_GROUPS": "action",
            "TESTGAME_TRACE": "viewer",
            "TESTGAME_TRACE_GROUPS": "state",
            "TESTGAME_TRACE_INCLUDE": "custom",
            "TESTGAME_TRACE_EXCLUDE": "phase_skip",
        }
    )

    assert trace_config.level == "viewer"
    assert trace_config.groups == frozenset({"state"})
    assert trace_config.targets_event("domain.phase_start")
    assert trace_config.targets_event("domain.custom")
    assert not trace_config.targets_event("act_wait")
    assert trace_config.excludes_event("domain.phase_skip")
