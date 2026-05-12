from __future__ import annotations

from enum import Enum


class Role(Enum):
    MINER = "miner"
    SCOUT = "scout"
    ALIGNER = "aligner"
    SCRAMBLER = "scrambler"


ROLE_TO_STATION: dict[Role, str] = {
    Role.MINER: "miner",
    Role.SCOUT: "scout",
    Role.ALIGNER: "aligner",
    Role.SCRAMBLER: "scrambler",
}

ROLE_TO_GEAR: dict[Role, str] = {
    Role.MINER: "miner",
    Role.SCOUT: "scout",
    Role.ALIGNER: "aligner",
    Role.SCRAMBLER: "scrambler",
}

ROLE_VIBES = ["miner", "scout", "aligner", "scrambler"]

VIBE_TO_ROLE: dict[str, Role] = {
    "miner": Role.MINER,
    "scout": Role.SCOUT,
    "aligner": Role.ALIGNER,
    "scrambler": Role.SCRAMBLER,
}
