from __future__ import annotations

from io import BytesIO
import json
import math
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

GRADER_ID = "cogs-v-clips-grader"
CORE_RESOURCES = frozenset({"oxygen", "carbon", "germanium", "silicon"})
ROLE_RESOURCES = frozenset({"aligner", "scrambler", "miner", "scout"})


def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        with urllib.request.urlopen(uri) as response:
            return response.read()
    if parsed.scheme == "s3":
        return read_s3_uri(parsed.netloc, parsed.path)
    path = Path(unquote(parsed.path) if parsed.scheme == "file" else uri)
    return path.read_bytes()


def write_uri(uri: str, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(
            uri,
            data=encoded,
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            response.read()
        return
    if parsed.scheme == "s3":
        write_s3_uri(parsed.netloc, parsed.path, encoded)
        return
    path = Path(unquote(parsed.path) if parsed.scheme == "file" else uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def read_s3_uri(bucket: str, key_path: str) -> bytes:
    if not bucket or not key_path.strip("/"):
        raise ValueError("s3 URI must include a bucket and key")
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("s3 URI support requires boto3") from exc

    response = boto3.client("s3").get_object(Bucket=bucket, Key=key_path.lstrip("/"))
    return response["Body"].read()


def write_s3_uri(bucket: str, key_path: str, content: bytes) -> None:
    if not bucket or not key_path.strip("/"):
        raise ValueError("s3 URI must include a bucket and key")
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("s3 URI support requires boto3") from exc

    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key_path.lstrip("/"),
        Body=content,
        ContentType="application/json",
    )


def load_bundle_artifacts(bundle_content: bytes) -> tuple[dict[str, object], dict[str, object]]:
    with zipfile.ZipFile(BytesIO(bundle_content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        if not isinstance(manifest, dict):
            raise TypeError("bundle manifest.json must contain a JSON object")
        results = json.loads(bundle.read(bundle_file(manifest, "results", "results.json")))
        replay = json.loads(bundle.read(bundle_file(manifest, "replay", "replay.json")))
    if not isinstance(results, dict):
        raise TypeError("results artifact must contain a JSON object")
    if not isinstance(replay, dict):
        raise TypeError("replay artifact must contain a JSON object")
    return results, replay


def bundle_file(manifest: dict[str, object], token: str, fallback: str) -> str:
    files = manifest.get("files")
    if isinstance(files, dict) and isinstance(files.get(token), str):
        return files[token]
    return fallback


def cogs_v_clips_interestingness(results: dict[str, object], replay: dict[str, object]) -> float:
    objects = replay.get("objects")
    if not isinstance(objects, list):
        raise ValueError("Cogs vs Clips replay must include an objects list")

    agents = [obj for obj in objects if isinstance(obj, dict) and is_agent(obj)]
    item_names = replay_item_names(replay)

    score_signal = max(
        normalized_spread(numeric_list(results.get("scores"))),
        normalized_spread(agent_total_rewards(agents)),
        normalized_spread(replay_episode_rewards(replay)),
    )
    inventory_signal = normalized_spread(agent_inventory_activity(agents, item_names))
    role_survival_signal = max(
        normalized_spread(agent_role_activity(agents, item_names)),
        survival_signal(agents, item_names),
    )
    junction_signal = junction_activity_signal(objects, replay_tags(replay))

    score = (
        0.35 * score_signal
        + 0.30 * inventory_signal
        + 0.20 * role_survival_signal
        + 0.15 * junction_signal
    )
    return round(clamp(score), 4)


def is_history(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    steps: list[float] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return False
        step = item[0]
        if isinstance(step, bool) or not isinstance(step, (int, float)):
            return False
        steps.append(float(step))
    return steps[0] == 0.0 and steps == sorted(steps)


def all_values(value: object) -> list[object]:
    if is_history(value):
        return [item[1] for item in value]  # type: ignore[index]
    return [value]


def first_value(value: object) -> object:
    return all_values(value)[0]


def last_value(value: object) -> object:
    return all_values(value)[-1]


def numeric_list(value: object) -> list[float]:
    if not isinstance(value, list):
        return []
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        number = float(item)
        if math.isfinite(number):
            numbers.append(number)
    return numbers


def normalized_spread(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    high = max(values)
    low = min(values)
    return clamp((high - low) / max(abs(high), abs(low), 1.0))


def is_agent(obj: dict[str, object]) -> bool:
    if last_value(obj.get("is_agent")) is True:
        return True
    agent_id = last_value(obj.get("agent_id"))
    return isinstance(agent_id, int) and not isinstance(agent_id, bool)


def replay_item_names(replay: dict[str, object]) -> list[str]:
    item_names = replay.get("item_names")
    if not isinstance(item_names, list):
        return []
    return [item for item in item_names if isinstance(item, str)]


def replay_tags(replay: dict[str, object]) -> dict[str, int]:
    tags = replay.get("tags")
    if not isinstance(tags, dict):
        return {}
    return {key: value for key, value in tags.items() if isinstance(key, str) and isinstance(value, int)}


def replay_episode_rewards(replay: dict[str, object]) -> list[float]:
    infos = replay.get("infos")
    if not isinstance(infos, dict):
        return []
    return numeric_list(infos.get("episode_rewards"))


def agent_total_rewards(agents: list[dict[str, object]]) -> list[float]:
    rewards: list[float] = []
    for agent in agents:
        value = last_value(agent.get("total_reward"))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        reward = float(value)
        if math.isfinite(reward):
            rewards.append(reward)
    return rewards


def agent_inventory_activity(agents: list[dict[str, object]], item_names: list[str]) -> list[float]:
    return [
        peak_inventory_total(agent, item_names, CORE_RESOURCES) + 2.0 * peak_inventory_total(agent, item_names, {"heart"})
        for agent in agents
    ]


def peak_inventory_total(agent: dict[str, object], item_names: list[str], resource_names: set[str] | frozenset[str]) -> float:
    peak = 0.0
    for inventory in inventory_values(agent.get("inventory", [])):
        amounts = inventory_amounts(inventory, item_names)
        total = sum(amounts.get(resource_name, 0.0) for resource_name in resource_names)
        peak = max(peak, total)
    return peak


def inventory_values(value: object) -> list[object]:
    if is_history(value) and all(isinstance(item[1], (dict, list)) for item in value):  # type: ignore[index]
        return [item[1] for item in value]  # type: ignore[index]
    return [value]


def inventory_amounts(inventory: object, item_names: list[str]) -> dict[str, float]:
    amounts: dict[str, float] = {}
    if isinstance(inventory, dict):
        iterable = inventory.items()
    elif isinstance(inventory, list):
        iterable = (pair for pair in inventory if isinstance(pair, (list, tuple)) and len(pair) == 2)
    else:
        return amounts

    for raw_name, raw_amount in iterable:
        name = item_name(raw_name, item_names)
        if name is None or isinstance(raw_amount, bool) or not isinstance(raw_amount, (int, float)):
            continue
        amounts[name] = amounts.get(name, 0.0) + float(raw_amount)
    return amounts


def item_name(raw_name: object, item_names: list[str]) -> str | None:
    if isinstance(raw_name, bool):
        return None
    if isinstance(raw_name, int):
        return item_names[raw_name] if 0 <= raw_name < len(item_names) else None
    if isinstance(raw_name, float) and raw_name.is_integer():
        index = int(raw_name)
        return item_names[index] if 0 <= index < len(item_names) else None
    if isinstance(raw_name, str):
        if raw_name.isdigit():
            index = int(raw_name)
            return item_names[index] if 0 <= index < len(item_names) else None
        return raw_name
    return None


def agent_role_activity(agents: list[dict[str, object]], item_names: list[str]) -> list[float]:
    return [float(role_gear_count(agent, item_names) + vibe_role_count(agent, item_names)) for agent in agents]


def role_gear_count(agent: dict[str, object], item_names: list[str]) -> int:
    held_roles: set[str] = set()
    for inventory in inventory_values(agent.get("inventory", [])):
        amounts = inventory_amounts(inventory, item_names)
        held_roles.update(role for role in ROLE_RESOURCES if amounts.get(role, 0.0) > 0.0)
    return len(held_roles)


def vibe_role_count(agent: dict[str, object], item_names: list[str]) -> int:
    roles: set[str] = set()
    for field_name in ("vibe", "vibe_id"):
        for value in all_values(agent.get(field_name)):
            name = item_name(value, item_names)
            if name in ROLE_RESOURCES:
                roles.add(name)
    return len(roles)


def survival_signal(agents: list[dict[str, object]], item_names: list[str]) -> float:
    if len(agents) < 2:
        return 0.0

    died = [False in all_values(agent.get("alive", True)) for agent in agents]
    survived = [last_value(agent.get("alive", True)) is not False for agent in agents]
    death_divergence = 1.0 if any(died) and any(survived) else 0.0

    final_hp: list[float] = []
    min_hp: list[float] = []
    for agent in agents:
        hp_values = agent_hp_values(agent, item_names)
        if not hp_values:
            continue
        final_hp.append(hp_values[-1])
        min_hp.append(min(hp_values))

    hp_signal = max(normalized_spread(final_hp), normalized_spread(min_hp))
    return clamp(0.6 * death_divergence + 0.4 * hp_signal)


def agent_hp_values(agent: dict[str, object], item_names: list[str]) -> list[float]:
    values: list[float] = []
    for inventory in inventory_values(agent.get("inventory", [])):
        amount = inventory_amounts(inventory, item_names).get("hp")
        if amount is not None:
            values.append(amount)
    return values


def junction_activity_signal(objects: list[object], tags: dict[str, int]) -> float:
    junctions = [obj for obj in objects if isinstance(obj, dict) and is_junction(obj, tags)]
    if not junctions:
        return 0.0
    changed = sum(
        1
        for junction in junctions
        if sequence_changed(all_values(junction.get("color"))) or sequence_changed(tag_id_values(junction.get("tag_ids")))
    )
    return clamp(changed / len(junctions))


def is_junction(obj: dict[str, object], tags: dict[str, int]) -> bool:
    if last_value(obj.get("type_name")) == "junction":
        return True
    junction_tag = tags.get("type:junction")
    tag_ids = tag_id_values(obj.get("tag_ids"))[-1]
    return junction_tag is not None and isinstance(tag_ids, list) and junction_tag in tag_ids


def tag_id_values(value: object) -> list[object]:
    if is_history(value) and all(isinstance(item[1], list) for item in value):  # type: ignore[index]
        return [item[1] for item in value]  # type: ignore[index]
    return [value]


def sequence_changed(values: list[object]) -> bool:
    if len(values) < 2:
        return False
    encoded_values = {json.dumps(item, sort_keys=True) for item in values}
    return len(encoded_values) > 1


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def main() -> None:
    results, replay = load_bundle_artifacts(read_uri(os.environ["COGAME_EPISODE_BUNDLE_URI"]))
    score = cogs_v_clips_interestingness(results, replay)
    write_uri(os.environ["COGAME_GRADE_URI"], {"grader_id": GRADER_ID, "score": score})
    print(f"wrote Cogs vs Clips grade {score}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
