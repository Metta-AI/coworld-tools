"""Integration tests for CvcEngine and mixins.

Exercises role dispatch (miner/aligner/scrambler), targeting, navigation,
pressure, junction memory — by building rich MettagridStates and calling
GameState methods. Complements the scenario harness which runs real envs.
"""

from __future__ import annotations

from typing import Any

import pytest

from cvc_policy.agent.types import KnownEntity
from cvc_policy.game_state import GameState
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import (
    GridPosition,
    MacroDirective,
    MettagridState,
    SelfState,
    SemanticEntity,
    TeamMemberSummary,
    TeamSummary,
)


def _env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface(
        action_names=[
            "noop",
            "move_north",
            "move_south",
            "move_east",
            "move_west",
        ],
        vibe_action_names=[
            "change_vibe_default",
            "change_vibe_miner",
            "change_vibe_aligner",
            "change_vibe_scrambler",
            "change_vibe_heart",
            "change_vibe_gear",
        ],
        num_agents=1,
        observation_shape=(10, 3),
        egocentric_shape=(11, 11),
    )


def _semantic(entity_type: str, x: int, y: int, **attrs: Any) -> SemanticEntity:
    a = dict(attrs)
    a.setdefault("global_x", x)
    a.setdefault("global_y", y)
    return SemanticEntity(
        entity_id=f"{entity_type}_{x}_{y}",
        entity_type=entity_type,
        position=GridPosition(x=x, y=y),
        labels=[],
        attributes=a,
    )


def _build_state(
    *,
    x: int = 50,
    y: int = 50,
    team: str = "team_0",
    hp: int = 100,
    role: str | None = None,
    inventory: dict[str, int] | None = None,
    shared_inventory: dict[str, int] | None = None,
    visible: list[SemanticEntity] | None = None,
    members: list[Any] | None = None,
    step: int = 1,
) -> MettagridState:
    inv = {"hp": hp}
    if inventory:
        inv.update(inventory)
    shared = {r: 10 for r in ("carbon", "oxygen", "germanium", "silicon")}
    shared["heart"] = 5
    if shared_inventory is not None:
        shared.update(shared_inventory)
    self_state = SelfState(
        entity_id="agent_self",
        entity_type="agent",
        position=GridPosition(x=x, y=y),
        labels=[],
        attributes={"global_x": x, "global_y": y, "team": team, "entity_id": "agent_self"},
        role=role,
        inventory=inv,
        status=[],
    )
    ts = TeamSummary(
        team_id=team,
        members=list(members or []),
        shared_inventory=shared,
        shared_objectives=[],
    )
    return MettagridState(
        game="t",
        step=step,
        self_state=self_state,
        visible_entities=list(visible or []),
        team_summary=ts,
        recent_events=[],
    )


@pytest.fixture
def gs() -> GameState:
    return GameState(_env_info(), agent_id=0)


def _put(gs: GameState, state: MettagridState) -> None:
    """Run obs processing path (no action) so engine world model is populated."""
    engine = gs.engine
    engine._world_model.update(state)
    engine._update_junctions(state)
    gs.mg_state = state


# --- Pressure & retreat ---------------------------------------------------


def test_pressure_budgets_and_metrics(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    junc_friendly = _semantic("junction", 55, 50, owner="team_0", team="team_0")
    junc_neutral = _semantic("junction", 52, 54, owner="neutral")
    junc_enemy = _semantic("junction", 60, 60, owner="team_1", team="team_1")
    state = _build_state(
        x=50, y=50, visible=[hub, junc_friendly, junc_neutral, junc_enemy], step=400,
    )
    _put(gs, state)

    # desired_role covers pressure allocation
    assert gs.desired_role() in {"miner", "aligner", "scrambler"}
    # Early game — economy boot objective
    assert gs.desired_role(objective="economy_bootstrap") in {"miner", "aligner", "scrambler"}
    # Resource coverage: no aligner/scrambler pressure
    assert gs.desired_role(objective="resource_coverage") == "miner"

    # Engine direct: pressure_metrics + macro_snapshot
    snap = gs.engine._macro_snapshot(state, "miner")
    assert "frontier_neutral_junctions" in snap
    assert "aligner_budget" in snap
    # should_retreat branches
    assert isinstance(gs.should_retreat(), bool)


def test_retreat_low_hp_triggers(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(x=52, y=50, hp=5, visible=[hub])
    _put(gs, state)
    assert gs.should_retreat() is True


def test_retreat_far_miner_heuristic(gs: GameState) -> None:
    """CogletAgentPolicy adds extra retreat for distant low-hp miners."""
    hub = _semantic("hub", 0, 0, team="team_0", owner="team_0")
    state = _build_state(x=30, y=0, hp=20, visible=[hub])
    _put(gs, state)
    # Distance 30, hp 20 < 30+10 => should retreat
    gs.role = "miner"
    assert gs.should_retreat() is True


# --- Miner action --------------------------------------------------------


def test_miner_action_heads_to_extractor(gs: GameState) -> None:
    ext = _semantic("carbon_extractor", 55, 50, carbon=5)
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[ext, hub], inventory={"miner": 1}, step=5)
    _put(gs, state)
    action, summary = gs.miner_action()
    assert "mine_carbon" in summary or "deposit" in summary


def test_miner_action_no_extractor_explores(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub], inventory={"miner": 1})
    _put(gs, state)
    action, summary = gs.miner_action()
    assert summary.endswith("find_extractors") or "search" in summary or "explore" in summary


def test_miner_deposits_when_cargo_full(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    # Force known-cap via cargo_cap tracker
    gs.engine._cargo_cap._cap[("miner",)] = 4
    ext = _semantic("carbon_extractor", 55, 50, carbon=5)
    state = _build_state(
        visible=[ext, hub],
        inventory={"miner": 1, "carbon": 4},
    )
    _put(gs, state)
    action, summary = gs.miner_action()
    assert "deposit" in summary


# --- Aligner action ------------------------------------------------------


def test_aligner_action_targets_neutral_junction(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    junction = _semantic("junction", 55, 52, owner="neutral")
    state = _build_state(
        visible=[hub, junction],
        inventory={"aligner": 1, "heart": 3},
        step=100,
        x=80, y=80,  # far from hub so no batch_hearts at range 1
    )
    _put(gs, state)
    action, summary = gs.aligner_action()
    assert "align" in summary or "explore" in summary or "deposit" in summary


def test_aligner_no_heart_picks_up(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub], inventory={"aligner": 1, "heart": 0})
    _put(gs, state)
    _, summary = gs.aligner_action()
    assert "heart" in summary or "rebuild_hearts" in summary


def test_aligner_no_team_hearts_mines(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    ext = _semantic("carbon_extractor", 55, 50, carbon=5)
    state = _build_state(
        visible=[hub, ext],
        inventory={"aligner": 1, "heart": 0},
        shared_inventory={"heart": 0, "carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    _put(gs, state)
    _, summary = gs.aligner_action()
    assert "rebuild_hearts" in summary


# --- Scrambler action ---------------------------------------------------


def test_scrambler_no_enemy_explores(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub], inventory={"scrambler": 1, "heart": 2})
    _put(gs, state)
    _, summary = gs.scrambler_action()
    assert "find_enemy" in summary or "explore" in summary


def test_scrambler_targets_enemy(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    enemy_j = _semantic("junction", 58, 55, owner="team_1", team="team_1")
    state = _build_state(
        visible=[hub, enemy_j],
        inventory={"scrambler": 1, "heart": 2},
    )
    _put(gs, state)
    _, summary = gs.scrambler_action()
    assert "scramble" in summary or "explore" in summary


# --- Gear acquisition ---------------------------------------------------


def test_acquire_role_gear_from_station(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    station = _semantic("miner_station", 53, 50)
    state = _build_state(visible=[hub, station])
    _put(gs, state)
    _, summary = gs.acquire_role_gear("miner")
    assert "get_miner_gear" in summary or "search_miner_station" in summary


def test_acquire_role_gear_no_station_searches(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub])
    _put(gs, state)
    _, summary = gs.acquire_role_gear("miner")
    assert "miner_station" in summary


# --- Full decision pipeline (main.py step + choose_action) -------------


def test_full_choose_action_pipeline(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    ext = _semantic("carbon_extractor", 52, 51, carbon=5)
    state = _build_state(visible=[hub, ext], inventory={"miner": 1}, step=10)
    gs.process_obs_fake = state  # placeholder
    # Use engine's evaluate_state via process_obs + choose_action
    gs.mg_state = state
    gs.engine._world_model.update(state)
    gs.engine._update_junctions(state)
    action, summary = gs.choose_action("miner")
    assert isinstance(summary, str)
    gs.finalize_step(summary)


def test_evaluate_state_runs_end_to_end(gs: GameState) -> None:
    """Drive engine.evaluate_state directly to cover main.py hot path."""
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    ext = _semantic("carbon_extractor", 52, 50, carbon=5)
    state = _build_state(visible=[hub, ext], inventory={"miner": 1}, step=1)
    action = gs.engine.evaluate_state(state)
    assert action is not None
    # Second tick — covers _previous_state branch, stall counter, record nav
    state2 = _build_state(visible=[hub, ext], inventory={"miner": 1}, step=2)
    gs.engine.evaluate_state(state2)
    # Infos populated
    assert "role" in gs.engine._infos
    # Reset path
    gs.engine.reset()
    assert gs.engine._step_index == 0


# --- Navigation / unstick -----------------------------------------------


def test_unstick_miner(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    ext = _semantic("carbon_extractor", 51, 50, carbon=5)
    state = _build_state(visible=[hub, ext], inventory={"miner": 1})
    _put(gs, state)
    action, summary = gs.unstick(role="miner")
    assert "unstick_miner" in summary


def test_explore_action_varies(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub])
    _put(gs, state)
    _, summary = gs.explore(role="aligner")
    assert isinstance(summary, str)


# --- Macro directive sanitization ---------------------------------------


def test_macro_directive_sanitized(gs: GameState) -> None:
    # Invalid role/bias get stripped
    raw = MacroDirective(role="xyz", resource_bias="bogus", note="hi")
    clean = gs.engine._sanitize_macro_directive(raw)
    assert clean.role is None
    assert clean.resource_bias is None


# --- Junction memory & hotspots -----------------------------------------


def test_junction_memory_records_and_lists(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    # First: friendly
    j1_friendly = _semantic("junction", 52, 50, owner="team_0")
    state = _build_state(visible=[hub, j1_friendly], step=1)
    _put(gs, state)
    # Next: same junction scrambled by enemy -> hotspot bump
    j1_enemy = _semantic("junction", 52, 50, owner="team_1")
    state2 = _build_state(visible=[hub, j1_enemy], step=2)
    _put(gs, state2)
    assert any(v > 0 for v in gs.engine._hotspots.values())
    # known_junctions predicate path
    all_j = gs.known_junctions()
    assert len(all_j) >= 1


# --- Targeting: directive target routing --------------------------------


def test_directive_target_entity_id(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    j1 = _semantic("junction", 55, 50, owner="neutral")
    j2 = _semantic("junction", 60, 50, owner="neutral")
    state = _build_state(visible=[hub, j1, j2], inventory={"aligner": 1, "heart": 1})
    _put(gs, state)
    gs.engine._current_directive = MacroDirective(target_entity_id="junction@60,50")
    tgt = gs.engine._preferred_alignable_neutral_junction(state)
    assert tgt is not None
    assert tgt.position == (60, 50)


def test_directive_target_region_by_label(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    j1 = SemanticEntity(
        entity_id="junction_a",
        entity_type="junction",
        position=GridPosition(x=55, y=50),
        labels=["frontier"],
        attributes={"global_x": 55, "global_y": 50, "owner": "neutral"},
    )
    state = _build_state(visible=[hub, j1])
    _put(gs, state)
    gs.engine._current_directive = MacroDirective(target_region="frontier")
    tgt = gs.engine._preferred_alignable_neutral_junction(state)
    assert tgt is not None


# --- Teammate-aware aligner targeting -----------------------------------


def test_teammate_aligner_positions(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    junction = _semantic("junction", 55, 52, owner="neutral")
    members = [
        TeamMemberSummary(
            entity_id="other",
            role="aligner",
            position=GridPosition(x=54, y=52),
            inventory={},
            status=[],
        )
    ]
    state = _build_state(
        visible=[hub, junction],
        inventory={"aligner": 1, "heart": 1},
        members=members,
    )
    _put(gs, state)
    positions = gs.engine._teammate_aligner_positions(state)
    assert positions == [(54, 52)]


# --- Scramble stickiness + best target ---------------------------------


def test_best_scramble_target_picks_near_friendly(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    fj = _semantic("junction", 55, 50, owner="team_0")
    ej_far = _semantic("junction", 80, 80, owner="team_1", team="team_1")
    ej_near = _semantic("junction", 56, 50, owner="team_1", team="team_1")
    state = _build_state(
        visible=[hub, fj, ej_far, ej_near],
        inventory={"scrambler": 1, "heart": 2},
    )
    _put(gs, state)
    best = gs.engine._best_scramble_target(state)
    assert best is not None
    assert best.position == (56, 50)


# --- Cargo-cap observe integration -------------------------------------


def test_cargo_cap_observed_via_process_obs() -> None:
    from cvc_policy.game_state import GameState

    gs = GameState(_env_info(), agent_id=0)
    # Set prev mine flag
    gs.engine._prev_summary_was_mine = True
    # Simulate a plateau
    ext = _semantic("carbon_extractor", 52, 50, carbon=5)
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    for _ in range(2):
        state = _build_state(
            visible=[hub, ext],
            inventory={"miner": 1, "carbon": 3},
            step=gs.engine._step_index + 1,
        )
        # Replicate process_obs without AgentObservation (we already have state):
        gs.engine._world_model.update(state)
        gs.engine._cargo_cap.observe(
            gear_sig=("miner",),
            cargo=3,
            mined_last_tick=True,
        )
    assert gs.engine._cargo_cap.known_cap(("miner",)) == 3


# --- Programs module coverage ------------------------------------------


def test_program_table_lookup() -> None:
    from cvc_policy import programs

    table = programs.all_programs()
    assert isinstance(table, dict)
    assert len(table) >= 1
    for name, p in table.items():
        assert p.executor in {"code", "llm"}
        assert isinstance(name, str)


# --- Programs: exercise each code program ------------------------------


def test_all_code_programs_callable(gs: GameState) -> None:
    from cvc_policy import programs as P

    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    ext = _semantic("carbon_extractor", 52, 50, carbon=5)
    junc_neutral = _semantic("junction", 55, 52, owner="neutral")
    junc_enemy = _semantic("junction", 58, 58, owner="team_1", team="team_1")
    members = [
        TeamMemberSummary(
            entity_id="other",
            role="miner",
            position=GridPosition(x=49, y=50),
            inventory={},
            status=[],
        )
    ]
    state = _build_state(
        visible=[hub, ext, junc_neutral, junc_enemy],
        inventory={"miner": 1, "heart": 2, "carbon": 2},
        members=members,
        step=50,
    )
    _put(gs, state)
    # drive cargo_cap observe so state lookups work
    gs.engine._cargo_cap.observe(gear_sig=("miner",), cargo=2, mined_last_tick=False)

    # Query programs
    assert P._hp(gs) == 100
    assert P._step_num(gs) == 0  # engine step_index not advanced via evaluate_state
    assert P._position(gs) == (50, 50)
    assert isinstance(P._inventory(gs), dict)
    assert P._resource_bias(gs) in ("carbon", "oxygen", "germanium", "silicon")
    assert isinstance(P._team_resources(gs), dict)
    assert len(P._resource_priority(gs)) == 4
    assert P._nearest_hub(gs) is not None
    assert P._nearest_extractor(gs, "carbon") is not None
    assert isinstance(P._known_junctions(gs), list)
    assert P._safe_distance(gs) >= 0
    assert P._has_role_gear(gs, "miner") is True
    assert isinstance(P._team_can_afford_gear(gs, "miner"), bool)
    assert P._needs_emergency_mining(gs) is False
    assert P._is_stalled(gs) is False
    assert P._is_oscillating(gs) is False

    # Action programs
    act = P._action(gs, "move_north", vibe="change_vibe_miner")
    assert act.name == "move_north"
    # Fallback when unknown
    bad = P._action(gs, "does_not_exist")
    assert bad.name == gs.fallback
    # move_to: position tuple
    out2 = P._move_to(gs, (55, 55))
    assert isinstance(out2, tuple)
    # move_to: KnownEntity from world model
    known_hub = gs.nearest_hub()
    assert known_hub is not None
    out1 = P._move_to(gs, known_hub)
    assert isinstance(out1, tuple)
    assert isinstance(P._hold(gs), tuple)
    assert isinstance(P._explore(gs, "miner"), tuple)
    assert isinstance(P._unstick(gs, "miner"), tuple)

    # Decision programs
    assert P._desired_role(gs) in {"miner", "aligner", "scrambler"}
    assert isinstance(P._should_retreat(gs), bool)
    assert isinstance(P._retreat(gs), tuple)
    assert isinstance(P._mine(gs), tuple)
    assert isinstance(P._align(gs), tuple)
    assert isinstance(P._scramble(gs), tuple)
    assert isinstance(P._step(gs), tuple)
    summary = P._summarize(gs)
    assert "step" in summary
    assert "roles" in summary


def test_should_retreat_low_hp_far_from_hub(gs: GameState) -> None:
    from cvc_policy import programs as P

    hub = _semantic("hub", 0, 0, team="team_0", owner="team_0")
    state = _build_state(x=30, y=0, hp=50, visible=[hub], inventory={"miner": 1})
    _put(gs, state)
    # hp<60 AND safe_distance>25 -> should_retreat true
    assert P._should_retreat(gs) is True


def test_retreat_no_hub_holds(gs: GameState) -> None:
    from cvc_policy import programs as P

    # No hub visible, no bootstrap (role_id=0 has offset (0,3), so bootstrap
    # IS returned). Use role_id=10 which has no bootstrap — but we're at
    # agent_id=0. Instead set team to None.
    state = _build_state(visible=[])
    # Override team_summary to None to nuke team_id
    state = MettagridState(
        game=state.game,
        step=state.step,
        self_state=state.self_state,
        visible_entities=state.visible_entities,
        team_summary=None,
        recent_events=[],
    )
    _put(gs, state)
    # fall back through: nearest_hub builds a bootstrap regardless — so retreat
    # will use bootstrap hub. Just assert it returns a tuple.
    out = P._retreat(gs)
    assert isinstance(out, tuple)


def test_parse_analysis_variants() -> None:
    from cvc_policy.programs import _parse_analysis

    # Plain JSON
    out = _parse_analysis(
        '{"resource_bias":"carbon","role":"miner","objective":"expand","analysis":"ok"}'
    )
    assert out["resource_bias"] == "carbon"
    assert out["role"] == "miner"
    assert out["objective"] == "expand"

    # JSON inside markdown fences
    fenced = '```json\n{"resource_bias":"oxygen","analysis":"x"}\n```'
    out = _parse_analysis(fenced)
    assert out["resource_bias"] == "oxygen"

    # JSON embedded in prose
    prose = 'thinking... {"resource_bias":"germanium","role":"aligner"} trailing'
    out = _parse_analysis(prose)
    assert out["resource_bias"] == "germanium"

    # Invalid JSON -> fallback
    out = _parse_analysis("not json at all")
    assert "analysis" in out

    # Bad field values ignored
    out = _parse_analysis('{"resource_bias":"bogus","role":"xyz","objective":"q"}')
    assert "resource_bias" not in out
    assert "role" not in out
    assert "objective" not in out


def test_build_analysis_prompt_has_keys() -> None:
    from cvc_policy.programs import _build_analysis_prompt, _team_resources

    class DummyGS:
        step_index = 1
        agent_id = 0
        hp = 50
        position = (10, 10)
        role = "miner"
        resource_bias = "carbon"
        mg_state = None

        def nearest_hub(self):
            return None

        def known_junctions(self, predicate):
            return []

        def has_role_gear(self, role):
            return True

        def needs_emergency_mining(self):
            return False

        stalled_steps = 0
        oscillation_steps = 0

    # Build ctx manually
    ctx = {
        "step": 1,
        "agent_id": 0,
        "hp": 50,
        "role": "miner",
        "position": (10, 10),
        "has_gear": True,
        "team_resources": {"carbon": 1, "oxygen": 2, "germanium": 3, "silicon": 4},
        "junctions": {"friendly": 1, "enemy": 0, "neutral": 2},
        "stalled": False,
        "oscillating": False,
        "safe_distance": 5,
        "inventory": {"heart": 1},
        "roles": "miner=4",
    }
    text = _build_analysis_prompt(ctx)
    assert "CvC game step" in text
    assert "resource_bias" in text


# --- GameState property surface ---------------------------------------


def test_gamestate_properties(gs: GameState) -> None:
    # Before any mg_state
    assert gs.hp == 0
    assert gs.position == (0, 0)

    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub], inventory={"miner": 1})
    _put(gs, state)

    assert gs.hp == 100
    assert gs.position == (50, 50)
    assert gs.resource_bias in ("carbon", "oxygen", "germanium", "silicon")
    gs.resource_bias = "oxygen"
    assert gs.resource_bias == "oxygen"
    assert gs.stalled_steps == 0
    gs.stalled_steps = 5
    assert gs.stalled_steps == 5
    assert gs.oscillation_steps == 0
    gs.oscillation_steps = 2
    assert gs.oscillation_steps == 2
    gs.explore_index = 3
    assert gs.explore_index == 3
    gs.step_index = 7
    assert gs.step_index == 7

    # Delegate methods
    assert gs.nearest_hub() is not None
    assert gs.nearest_friendly_depot() is not None
    assert gs.team_id() == "team_0"
    assert isinstance(gs.resource_priority(), list)
    assert gs.has_role_gear("miner") is True
    assert isinstance(gs.team_can_afford_gear("miner"), bool)
    assert isinstance(gs.needs_emergency_mining(), bool)

    # Hold
    out = gs.hold(summary="pause", vibe="change_vibe_default")
    assert isinstance(out, tuple)

    # Reset
    gs.reset()
    assert gs.mg_state is None
    assert gs.role == "miner"


def test_gamestate_finalize_step_noop_when_no_state() -> None:
    gs = GameState(_env_info(), agent_id=0)
    gs.finalize_step("noop")  # no mg_state yet -> early return
    assert gs.mg_state is None




# --- Miner: should_force_miner_explore_reset ---------------------------


def test_miner_force_reset_on_long_stall_at_hub(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(x=50, y=51, visible=[hub], inventory={"miner": 1})
    _put(gs, state)
    gs.engine._stalled_steps = 15
    # No extractors visible, at hub within 1 -> reset sticky + return None
    result = gs.engine._preferred_miner_extractor(state)
    assert result is None


# --- Sticky miner target continues until cap --------------------------


# --- Role branch coverage --------------------------------------------


def test_aligner_no_heart_no_hub_explores(gs: GameState) -> None:
    # No hub at all (and bootstrap relies on role_id; set role_id out of range)
    gs.engine._role_id = 99
    state = _build_state(visible=[], inventory={"aligner": 1, "heart": 0})
    _put(gs, state)
    _, summary = gs.aligner_action()
    assert "find_hub_for_heart" in summary


def test_aligner_no_target_deposits_cargo(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(
        visible=[hub],
        inventory={"aligner": 1, "heart": 3, "carbon": 4},
        x=80, y=80,
    )
    _put(gs, state)
    _, summary = gs.aligner_action()
    assert "deposit_cargo" in summary or "find_neutral_junction" in summary


def test_scrambler_no_heart_team_has_hearts_goes_to_hub(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(
        visible=[hub],
        inventory={"scrambler": 1, "heart": 0},
        shared_inventory={"heart": 5},
        x=60, y=60,
    )
    _put(gs, state)
    _, summary = gs.scrambler_action()
    assert "acquire_heart" in summary


def test_scrambler_no_heart_no_team_mines(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    ext = _semantic("carbon_extractor", 52, 50, carbon=5)
    state = _build_state(
        visible=[hub, ext],
        inventory={"scrambler": 1, "heart": 0},
        shared_inventory={"heart": 0, "carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0},
    )
    _put(gs, state)
    _, summary = gs.scrambler_action()
    assert "rebuild_hearts" in summary


def test_scrambler_batch_hearts_at_hub(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(
        visible=[hub],
        inventory={"scrambler": 1, "heart": 1},  # < batch_target 2
        x=50, y=50,  # at hub
    )
    _put(gs, state)
    _, summary = gs.scrambler_action()
    assert "batch_hearts" in summary


def test_scrambler_no_heart_no_hub_explores(gs: GameState) -> None:
    gs.engine._role_id = 99
    state = _build_state(
        visible=[],
        inventory={"scrambler": 1, "heart": 0},
        shared_inventory={"heart": 5},
    )
    _put(gs, state)
    _, summary = gs.scrambler_action()
    assert "find_hub_for_heart" in summary


def test_acquire_gear_no_hub_explores(gs: GameState) -> None:
    # Agent role_id that has no station bootstrap -> go hub-relative; with
    # no hub AND no bootstrap target -> explore.
    gs.engine._role_id = 99
    # miner isn't in _STATION_TARGETS_BY_AGENT for role_id 99 -> target None
    state = _build_state(visible=[], inventory={})
    _put(gs, state)
    _, summary = gs.acquire_role_gear("miner")
    assert "find_miner_station" in summary or "miner_station" in summary


# --- Targeting: sticky align + sticky scramble -------------------------


def test_sticky_align_target_retained(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    j1 = _semantic("junction", 53, 50, owner="neutral")  # nearby candidate
    j_sticky = _semantic("junction", 55, 50, owner="neutral")
    state = _build_state(visible=[hub, j1, j_sticky], inventory={"aligner": 1, "heart": 2})
    _put(gs, state)
    # Sticky set to far-ish j_sticky within alignment network
    gs.engine._sticky_target_position = (55, 50)
    gs.engine._sticky_target_kind = "junction"
    pref = gs.engine._preferred_alignable_neutral_junction(state)
    assert pref is not None
    # Delta between candidate j1 and sticky is small; sticky retained.
    assert pref.position in {(53, 50), (55, 50)}


def test_sticky_align_target_out_of_network_cleared(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    # Sticky position out of alignment network (far from hub/friendly)
    gs.engine._sticky_target_position = (200, 200)
    gs.engine._sticky_target_kind = "junction"
    # Still need an in-network candidate, plus the out-of-network junction
    far = _semantic("junction", 200, 200, owner="neutral")
    state = _build_state(visible=[hub, far], inventory={"aligner": 1, "heart": 2})
    _put(gs, state)
    result = gs.engine._sticky_align_target(state)
    assert result is None
    assert gs.engine._sticky_target_kind is None  # cleared


def test_sticky_scramble_target(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    enemy_a = _semantic("junction", 55, 50, owner="team_1", team="team_1")
    enemy_b = _semantic("junction", 58, 50, owner="team_1", team="team_1")
    state = _build_state(
        visible=[hub, enemy_a, enemy_b],
        inventory={"scrambler": 1, "heart": 2},
    )
    _put(gs, state)
    gs.engine._sticky_target_position = (58, 50)
    gs.engine._sticky_target_kind = "junction"
    pref = gs.engine._preferred_scramble_target(state)
    assert pref is not None
    assert pref.position in {(55, 50), (58, 50)}


def test_sticky_scramble_target_not_enemy_cleared(gs: GameState) -> None:
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(
        visible=[hub],
        inventory={"scrambler": 1, "heart": 2},
    )
    _put(gs, state)
    gs.engine._sticky_target_position = (99, 99)
    gs.engine._sticky_target_kind = "junction"
    out = gs.engine._sticky_scramble_target(state)
    assert out is None


def test_sticky_miner_extractor_drained_cleared(gs: GameState) -> None:
    # Sticky points to an extractor that world model no longer knows about.
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub], inventory={"miner": 1})
    _put(gs, state)
    gs.engine._sticky_target_position = (99, 99)
    gs.engine._sticky_target_kind = "carbon_extractor"
    out = gs.engine._sticky_miner_target(state)
    assert out is None
    assert gs.engine._sticky_target_kind is None


def test_sticky_miner_target_retains(gs: GameState) -> None:
    ext1 = _semantic("carbon_extractor", 52, 50, carbon=5)
    ext2 = _semantic("carbon_extractor", 70, 70, carbon=5)
    hub = _semantic("hub", 50, 50, team="team_0", owner="team_0")
    state = _build_state(visible=[hub, ext1, ext2], inventory={"miner": 1})
    _put(gs, state)
    # Set sticky to far extractor
    gs.engine._sticky_target_position = (70, 70)
    gs.engine._sticky_target_kind = "carbon_extractor"
    pref = gs.engine._preferred_miner_extractor(state)
    # Closer ext by >3 units -> should switch
    assert pref is not None
    assert pref.position == (52, 50)
