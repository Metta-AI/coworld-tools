"""Integration tests for the perception module against live-captured frames.

These tests run parse_frame() against real frames captured from a live
Persephone's Escape game server and assert that the output matches
known-correct expected values.

Fixtures live in tests/fixtures/ as .npy (frame) + .json (expected) pairs.
See scripts/capture.py, scripts/view_timeline.py, and
scripts/extract_fixture.py for the capture and curation workflow.

Run:
    PYTHONPATH=. .venv/bin/python -m pytest tests/test_perception_live.py -v
"""

from __future__ import annotations

import pytest

from orpheus.perception import parse_frame
from orpheus.perception.types import View

from tests.conftest import (
    FixtureData,
    all_fixtures,
    assert_field,
    assert_fixture,
    fixture_ids,
    fixtures_for_view,
    load_manifest,
)


def _fixtures_for_view_or_skip(
    view: str,
    reason: str,
) -> tuple[list[FixtureData | pytest.ParameterSet], list[str]]:
    fixtures = fixtures_for_view(view)
    if fixtures:
        return fixtures, fixture_ids(fixtures)
    return [pytest.param(None, marks=pytest.mark.skip(reason=reason))], [f"no_{view}_fixture"]


# ---------------------------------------------------------------------------
# View detection tests -- every fixture must be classified correctly
# ---------------------------------------------------------------------------


class TestViewDetection:
    """Every fixture frame is classified to its expected view."""

    @pytest.fixture(params=all_fixtures(), ids=fixture_ids(all_fixtures()))
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_view_detected(self, fixture: FixtureData):
        """parse_frame() returns the correct view for this fixture."""
        result = parse_frame(fixture.frame)

        expected_view = View(fixture.view)

        if "view_detection_fails" in fixture.known_bugs:
            pytest.xfail(
                f"Known bug: view detection fails for {fixture.name} "
                f"(detected {result.view.value}, expected {fixture.view})"
            )

        assert result.view == expected_view, (
            f"Fixture '{fixture.name}': expected view={fixture.view}, "
            f"got view={result.view.value}"
        )


# ---------------------------------------------------------------------------
# Per-view assertion tests
# ---------------------------------------------------------------------------


class TestLobby:
    """Lobby view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("lobby"),
        ids=fixture_ids(fixtures_for_view("lobby")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)

        if "view_detection_fails" in fixture.known_bugs:
            pytest.xfail("Known bug: lobby view detection fails")

        assert_fixture(result, fixture)


class TestRoleReveal:
    """Role reveal view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("role_reveal"),
        ids=fixture_ids(fixtures_for_view("role_reveal")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_team_detected(self, fixture: FixtureData):
        """Team is detectable from the role-card panel's border color."""
        result = parse_frame(fixture.frame)
        assert result.view == View.ROLE_REVEAL
        assert result.role_reveal is not None
        if result.role_reveal.panel_index != 1:
            assert result.role_reveal.panel_index in (2, 3)
            return
        assert result.role_reveal.team is not None
        assert result.role_reveal.team_color is not None

    def test_role_name(self, fixture: FixtureData):
        """Role name extraction (known broken: _scan_centered bug)."""
        result = parse_frame(fixture.frame)
        assert result.role_reveal is not None

        if result.role_reveal.panel_index != 1:
            pytest.skip("Only the role-card panel renders the viewer's role name")

        if "role_name_not_extracted" in fixture.known_bugs:
            if result.role_reveal and result.role_reveal.role is None:
                pytest.xfail("Known bug: _scan_centered fails to extract role name")

        assert result.role_reveal.role is not None

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert_fixture(result, fixture)


class TestOverworld:
    """Overworld (playing) view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("playing"),
        ids=fixture_ids(fixtures_for_view("playing")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_view_and_overworld_populated(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.PLAYING
        assert result.overworld is not None

    def test_room_detected(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        if result.overworld:
            expected_room = fixture.assertions.get("overworld.room")
            if expected_room:
                actual = result.overworld.room
                assert actual is not None, "Room not detected"
                assert actual.value == expected_room

    def test_role_name(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)

        if "role_name_ocr_wrong" in fixture.known_bugs:
            expected = fixture.assertions.get("overworld.role_name")
            actual = result.overworld.role_name if result.overworld else None
            if actual != expected:
                pytest.xfail(
                    f"Known bug: role name OCR wrong "
                    f"(got {actual!r}, expected {expected!r})"
                )

        if result.overworld and "overworld.role_name" in fixture.assertions:
            assert_field(result, "overworld.role_name", fixture.assertions["overworld.role_name"])

    def test_assertions(self, fixture: FixtureData):
        """Run all fixture assertions (skipping known-buggy fields)."""
        result = parse_frame(fixture.frame)

        for path, spec in fixture.assertions.items():
            if path == "overworld.role_name" and "role_name_ocr_wrong" in fixture.known_bugs:
                continue  # Skip known-broken field
            if path.endswith("_count"):
                # Handle count assertions
                base_path = path[:-6] + "s"
                val = None
                parts = base_path.split(".")
                obj = result
                for part in parts:
                    obj = getattr(obj, part, None) if obj else None
                actual_count = len(obj) if obj is not None else 0
                if isinstance(spec, dict):
                    if "gte" in spec:
                        assert actual_count >= spec["gte"], (
                            f"{path}: expected >= {spec['gte']}, got {actual_count}"
                        )
                    if "lte" in spec:
                        assert actual_count <= spec["lte"], (
                            f"{path}: expected <= {spec['lte']}, got {actual_count}"
                        )
                else:
                    assert actual_count == spec, f"{path}: expected {spec}, got {actual_count}"
            else:
                assert_field(result, path, spec)


class TestChatroom:
    """Whisper/chatroom view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("whisper"),
        ids=fixture_ids(fixtures_for_view("whisper")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.WHISPER
        assert result.chatroom is not None
        assert_fixture(result, fixture)


class TestGlobalChat:
    """Global chat view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("global_chat"),
        ids=fixture_ids(fixtures_for_view("global_chat")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.GLOBAL_CHAT
        assert result.global_chat is not None
        assert_fixture(result, fixture)


class TestInfoScreen:
    """Info screen view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("info_screen"),
        ids=fixture_ids(fixtures_for_view("info_screen")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.INFO_SCREEN
        assert result.info_screen is not None
        assert_fixture(result, fixture)


class TestHostageExchange:
    """Hostage exchange view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("hostage_exchange"),
        ids=fixture_ids(fixtures_for_view("hostage_exchange")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.HOSTAGE_EXCHANGE
        assert result.exchange is not None
        assert_fixture(result, fixture)


class TestResult:
    """Reveal and game-over view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("reveal") + fixtures_for_view("game_over"),
        ids=fixture_ids(fixtures_for_view("reveal") + fixtures_for_view("game_over")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view in (View.REVEAL, View.GAME_OVER)
        assert result.result is not None
        assert_fixture(result, fixture)


class TestHostageSelect:
    """Hostage select view fixtures produce correct parsed output."""

    @pytest.fixture(
        params=fixtures_for_view("hostage_select"),
        ids=fixture_ids(fixtures_for_view("hostage_select")),
    )
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.HOSTAGE_SELECT
        assert result.overworld is not None
        assert_fixture(result, fixture)


class TestRosterReveal:
    """Roster reveal live fixtures produce correct parsed output."""

    _params, _ids = _fixtures_for_view_or_skip(
        "roster_reveal",
        "No live roster_reveal fixture available; synthetic coverage lives in test_perception_unit.py",
    )

    @pytest.fixture(params=_params, ids=_ids)
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.ROSTER_REVEAL
        assert result.roster_reveal is not None
        assert_fixture(result, fixture)


class TestLeaderSummit:
    """Leader summit live fixtures produce correct parsed output."""

    _params, _ids = _fixtures_for_view_or_skip(
        "leader_summit",
        "No live leader_summit fixture available; capture one from a leader summit phase",
    )

    @pytest.fixture(params=_params, ids=_ids)
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.LEADER_SUMMIT
        assert result.overworld is not None
        assert_fixture(result, fixture)


class TestWaitingEntry:
    """Waiting entry view fixtures produce correct parsed output."""

    _params, _ids = _fixtures_for_view_or_skip(
        "waiting_entry",
        "No live waiting_entry fixture available; capture one from a join-request flow",
    )

    @pytest.fixture(params=_params, ids=_ids)
    def fixture(self, request) -> FixtureData:
        return request.param

    def test_assertions(self, fixture: FixtureData):
        result = parse_frame(fixture.frame)
        assert result.view == View.WAITING_ENTRY
        assert result.overworld is not None
        assert_fixture(result, fixture)
