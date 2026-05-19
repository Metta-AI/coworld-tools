from __future__ import annotations

import re

from mettagrid_sdk.sdk import (
    HelperCapability,
    MettagridState,
    SemanticEntity,
    StateHelperCatalog,
)
from pydantic import BaseModel

_CALL_RE = re.compile(r"\b(?P<verb>vote|hunt) agent (?P<agent_id>\d+)\b")
_HEARD_SPEECH_RE = re.compile(r'^(?P<speaker>agent-\d+) said "(?P<text>.+)"$')


class HeardSpeechRecord(BaseModel):
    speaker_entity_id: str
    text: str
    step: int | None = None
    verb: str | None = None
    target_entity_id: str | None = None


_WEREWOLF_HELPER_CAPABILITIES = (
    ("phase", "Return the current phase, either day or night."),
    ("phase_step", "Return the current step count within the active day or night phase."),
    ("packmate_ids", "Return known werewolf packmate ids such as agent-4."),
    ("visible_players", "Return visible player entities, optionally filtering to alive players."),
    ("visible_player_ids", "Return visible player ids such as agent-3, optionally filtering to alive players."),
    ("meeting_bell", "Return the visible meeting bell entity when one is currently visible."),
    ("heard_speech", "Return recent heard-speech utterance texts from semantic events."),
    (
        "heard_speech_events",
        "Return recent heard-speech records including speaker, text, and any embedded vote or hunt target.",
    ),
    ("called_player_ids", "Return recent player ids mentioned in heard vote/hunt calls, optionally filtered by verb."),
    ("is_werewolf", "Return whether the current player is a werewolf."),
)


class WerewolfHelperCatalog(StateHelperCatalog):
    def __init__(self, state: MettagridState) -> None:
        super().__init__(
            state,
            capabilities=[
                *[
                    HelperCapability(name=name, description=description)
                    for name, description in _WEREWOLF_HELPER_CAPABILITIES
                ],
                *StateHelperCatalog(state).list_capabilities(),
            ],
        )

    def phase(self) -> str:
        return "day" if "day" in self._state.self_state.status else "night"

    def phase_step(self) -> int:
        value = self.self_attribute("phase_step", 0)
        return int(value) if isinstance(value, (int, float, str, bool)) else 0

    def packmate_ids(self) -> list[str]:
        return [
            objective.removeprefix("packmate:")
            for objective in self.shared_objectives()
            if objective.startswith("packmate:")
        ]

    def visible_players(self, *, alive_only: bool = True) -> list[SemanticEntity]:
        return [
            entity
            for entity in self.visible_entities(entity_type="agent")
            if not alive_only or int(entity.attributes.get("alive", 0)) > 0
        ]

    def visible_player_ids(self, *, alive_only: bool = True) -> list[str]:
        return [entity.entity_id for entity in self.visible_players(alive_only=alive_only)]

    def meeting_bell(self) -> SemanticEntity | None:
        return self.nearest_visible_entity(entity_type="meeting_bell")

    def heard_speech(self) -> list[str]:
        return [event.text for event in self.heard_speech_events()]

    def heard_speech_events(self) -> list[HeardSpeechRecord]:
        utterances: list[HeardSpeechRecord] = []
        for event in self._state.recent_events:
            if event.event_type != "heard_speech":
                continue
            match = _HEARD_SPEECH_RE.match(event.summary)
            if match is None:
                continue
            text = str(event.evidence[0]) if event.evidence else match.group("text")
            call_match = _CALL_RE.search(text.lower())
            utterances.append(
                HeardSpeechRecord(
                    speaker_entity_id=match.group("speaker"),
                    text=text,
                    step=event.step,
                    verb=None if call_match is None else call_match.group("verb"),
                    target_entity_id=(None if call_match is None else f"agent-{call_match.group('agent_id')}"),
                )
            )
        return utterances

    def called_player_ids(self, verb: str | None = None) -> list[str]:
        called: list[str] = []
        for utterance in self.heard_speech_events():
            if utterance.target_entity_id is None or utterance.verb is None:
                continue
            if verb is not None and utterance.verb != verb:
                continue
            called.append(utterance.target_entity_id)
        return called

    def is_werewolf(self) -> bool:
        return self._state.self_state.role == "werewolf"
