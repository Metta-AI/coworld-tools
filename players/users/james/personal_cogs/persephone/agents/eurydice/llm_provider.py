"""Provider adapters for Eurydice LLM control.

The real Bedrock provider intentionally uses only the Python standard library.
The local tournament venv does not guarantee ``anthropic`` or ``boto3`` will be
installed, while Softmax Bedrock access is exposed through ordinary AWS
credential mechanisms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION
from agents.eurydice.llm_prompts import build_prompt_parts, infer_surface


DEFAULT_BEDROCK_HAIKU_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"
BEDROCK_SERVICE = "bedrock"
AWS_CONTAINER_CREDENTIALS_ENDPOINT = "http://169.254.170.2"


class LLMProvider(Protocol):
    """Small provider interface used by the controller and shadow runner."""

    name: str
    decision_cooldown_ticks: int

    def decide(self, context: dict[str, Any], prompt: str) -> dict[str, Any]:
        """Return one raw decision object."""


@dataclass(frozen=True)
class HoldProvider:
    """Provider that always returns a valid hold decision."""

    name: str = "hold"
    decision_cooldown_ticks: int = 0

    def decide(self, context: dict[str, Any], prompt: str) -> dict[str, Any]:
        del context, prompt
        return _decision("hold", rationale="provider disabled")


@dataclass(frozen=True)
class HeuristicProvider:
    """Deterministic fake provider for tests and offline shadow plumbing."""

    name: str = "heuristic"
    decision_cooldown_ticks: int = 0

    def decide(self, context: dict[str, Any], prompt: str) -> dict[str, Any]:
        del prompt
        surface = infer_surface(context)
        if surface == "probe":
            strategy_target = _strategy_probe_target(context)
            if strategy_target is not None:
                if _target_recently_in_whisper(context, strategy_target):
                    return _decision(
                        "join_whisper",
                        target=strategy_target,
                        surface=surface,
                        rationale="join known strategic target's existing whisper",
                    )
                return _decision(
                    "probe_player",
                    target=strategy_target,
                    surface=surface,
                    rationale="prioritize known strategic target",
                )
            whisper_target = _first_recent_whisper_target(context)
            if whisper_target is not None:
                return _decision(
                    "join_whisper",
                    target=whisper_target,
                    surface=surface,
                    rationale="join existing whisper before opening another solo room",
                )
            target = _first_probe_target(context)
            if target is not None:
                return _decision(
                    "probe_player",
                    target=target,
                    surface=surface,
                    rationale="probe first known reachable target",
                )
        if surface == "whisper":
            pending = _pending_entry(context)
            if pending is not None:
                return _decision(
                    "grant_entry",
                    target=pending,
                    surface=surface,
                    rationale="grant visible pending entry for information",
                )
            role_offer = _first_offer(context, "role")
            if role_offer is not None:
                return _decision(
                    "accept_role",
                    target=role_offer,
                    reveal_role=True,
                    surface=surface,
                    rationale="accept active role offer",
                )
            color_offer = _first_offer(context, "color")
            if color_offer is not None:
                return _decision(
                    "accept_color",
                    target=color_offer,
                    reveal_color=True,
                    surface=surface,
                    rationale="accept active color offer",
                )
            occupant = _first_whisper_occupant(context)
            if occupant is not None:
                return _decision(
                    "send_whisper",
                    target=occupant,
                    message="ROLE SHARE?",
                    surface=surface,
                    rationale="ask occupant for mechanical role exchange",
                )
        if surface == "global":
            if _chat_cooldown(context) > 0:
                return _decision(
                    "hold",
                    surface=surface,
                    rationale="wait for chat cooldown",
                )
            return _decision(
                "send_global",
                message="STATUS?",
                surface=surface,
                rationale="ask room for concise status",
            )
        if surface == "hostage":
            targets = _first_hostage_targets(context)
            if targets:
                return _decision(
                    "select_hostage",
                    hostage_targets=targets,
                    surface=surface,
                    rationale="select first eligible hostage targets",
                )
        if surface == "summit":
            if _chat_cooldown(context) > 0:
                return _decision(
                    "hold",
                    surface=surface,
                    rationale="wait for chat cooldown",
                )
            return _decision(
                "send_whisper",
                message="SEND ME",
                surface=surface,
                rationale="request transfer during leader summit",
            )
        return _decision("hold", surface=surface, rationale="no useful safe action")


@dataclass(frozen=True)
class BedrockHaikuProvider:
    """AWS Bedrock Claude Haiku provider for live Eurydice control.

    The provider returns a syntactically valid ``hold`` decision on transport,
    credential, timeout, or JSON-parse failure. Semantic mistakes from a model
    response are left intact so the deterministic validator can reject and
    trace them.
    """

    name: str = "bedrock-haiku"
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    timeout_seconds: float | None = None
    decision_cooldown_ticks: int | None = None
    _invoke: Callable[["BedrockHaikuProvider", str, str], str] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", self.model or _bedrock_model())
        object.__setattr__(
            self,
            "max_tokens",
            max(64, self.max_tokens or _env_int("EURYDICE_LLM_MAX_TOKENS", 512)),
        )
        object.__setattr__(
            self,
            "temperature",
            _bounded_float(
                self.temperature
                if self.temperature is not None
                else _env_float("EURYDICE_LLM_TEMPERATURE", 0.2),
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "timeout_seconds",
            max(
                1.0,
                self.timeout_seconds
                if self.timeout_seconds is not None
                else _env_int("EURYDICE_LLM_TIMEOUT_MS", 12_000) / 1000.0,
            ),
        )
        object.__setattr__(
            self,
            "decision_cooldown_ticks",
            max(
                0,
                self.decision_cooldown_ticks
                if self.decision_cooldown_ticks is not None
                else _env_int("EURYDICE_LLM_COOLDOWN_TICKS", 48),
            ),
        )

    def decide(self, context: dict[str, Any], prompt: str) -> dict[str, Any]:
        del prompt
        surface = infer_surface(context)
        system_prompt, user_prompt = build_prompt_parts(context, surface=surface)
        try:
            text = (
                self._invoke(self, system_prompt, user_prompt)
                if self._invoke is not None
                else _invoke_bedrock_messages(self, system_prompt, user_prompt)
            )
        except BedrockProviderError as exc:
            return _decision(
                "hold",
                surface=surface,
                confidence=0.0,
                rationale=_clip(f"provider error: {exc}", 240),
            )
        except Exception as exc:  # defensive: never let provider faults kill play
            return _decision(
                "hold",
                surface=surface,
                confidence=0.0,
                rationale=_clip(f"provider exception: {type(exc).__name__}", 240),
            )

        parsed = _parse_decision_json(text)
        if parsed is None:
            return _decision(
                "hold",
                surface=surface,
                confidence=0.0,
                rationale="provider returned non-json decision",
            )
        return _normalize_provider_decision(parsed)


def make_provider(name: str | None) -> LLMProvider:
    """Build a provider by name."""

    normalized = (name or "hold").strip().lower()
    if normalized in {"off", "hold", "disabled"}:
        return HoldProvider()
    if normalized in {"heuristic", "fake"}:
        return HeuristicProvider()
    if normalized in {
        "bedrock",
        "bedrock-haiku",
        "haiku",
        "claude-haiku",
        "anthropic-bedrock",
        "real",
    }:
        return BedrockHaikuProvider()
    raise ValueError(f"unknown Eurydice LLM provider: {name!r}")


def _decision(
    action: str,
    *,
    surface: str | None = None,
    target: list[int] | None = None,
    destination: list[int] | None = None,
    hostage_targets: list[list[int]] | None = None,
    message: str | None = None,
    reveal_color: bool = False,
    reveal_role: bool = False,
    confidence: float = 0.7,
    rationale: str,
) -> dict[str, Any]:
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "action": action,
        "surface": surface,
        "target": target,
        "destination": destination,
        "hostage_targets": hostage_targets,
        "message": message,
        "reveal_color": reveal_color,
        "reveal_role": reveal_role,
        "confidence": confidence,
        "rationale": rationale,
    }


def _first_probe_target(context: dict[str, Any]) -> list[int] | None:
    failed = {
        tuple(item.get("target"))
        for item in (context.get("runtime") or {}).get("probe_failures", [])
        if isinstance(item, dict) and isinstance(item.get("target"), list)
    }
    for player in context.get("players") or []:
        if player.get("is_self"):
            continue
        target = player.get("player_id")
        if not _is_target(target) or tuple(target) in failed:
            continue
        if player.get("visible_position") or player.get("last_seen_position"):
            return [int(target[0]), int(target[1])]
    return None


def _strategy_probe_target(context: dict[str, Any]) -> list[int] | None:
    strategy = context.get("strategy") or {}
    objective = strategy.get("objective")
    if objective in {"complete_key_exchange", "find_key_partner"}:
        target = strategy.get("key_partner_id")
        if _is_target(target):
            return [int(target[0]), int(target[1])]

    for key in ("enemy_key_role_id", "verified_ally"):
        target = strategy.get(key)
        if _is_target(target):
            return [int(target[0]), int(target[1])]
    return None


def _target_recently_in_whisper(
    context: dict[str, Any],
    target: list[int],
) -> bool:
    current_tick = context.get("tick")
    for player in context.get("players") or []:
        if player.get("is_self"):
            continue
        player_id = player.get("player_id")
        if not _is_target(player_id) or list(player_id) != target:
            continue
        last_seen = player.get("last_seen_in_whisper_tick")
        if not isinstance(last_seen, int):
            return False
        return not isinstance(current_tick, int) or current_tick - last_seen <= 60
    return False


def _first_recent_whisper_target(context: dict[str, Any]) -> list[int] | None:
    failed = {
        tuple(item.get("target"))
        for item in (context.get("runtime") or {}).get("probe_failures", [])
        if isinstance(item, dict) and isinstance(item.get("target"), list)
    }
    current_tick = context.get("tick")
    for player in context.get("players") or []:
        if player.get("is_self"):
            continue
        target = player.get("player_id")
        if not _is_target(target) or tuple(target) in failed:
            continue
        last_seen = player.get("last_seen_in_whisper_tick")
        if not isinstance(last_seen, int):
            continue
        if isinstance(current_tick, int) and current_tick - last_seen > 60:
            continue
        return [int(target[0]), int(target[1])]
    return None


def _pending_entry(context: dict[str, Any]) -> list[int] | None:
    pending = (context.get("runtime") or {}).get("pending_entry")
    if not isinstance(pending, dict):
        return None
    target = pending.get("player_id")
    return [int(target[0]), int(target[1])] if _is_target(target) else None


def _first_offer(context: dict[str, Any], kind: str) -> list[int] | None:
    field = "active_role_offers" if kind == "role" else "active_color_offers"
    for item in (context.get("runtime") or {}).get(field) or []:
        if not isinstance(item, dict):
            continue
        target = item.get("player_id")
        if _is_target(target):
            return [int(target[0]), int(target[1])]
    return None


def _first_whisper_occupant(context: dict[str, Any]) -> list[int] | None:
    for player in context.get("players") or []:
        target = player.get("player_id")
        if player.get("in_current_whisper") and not player.get("is_self") and _is_target(target):
            return [int(target[0]), int(target[1])]
    return None


def _first_hostage_targets(context: dict[str, Any]) -> list[list[int]]:
    options = ((context.get("runtime") or {}).get("hostage_options") or {})
    remaining = options.get("remaining_count")
    if not isinstance(remaining, int) or remaining <= 0:
        return []

    targets: list[list[int]] = []
    for option in options.get("options") or []:
        if not isinstance(option, dict) or option.get("selected"):
            continue
        player_id = option.get("player_id")
        if _is_target(player_id):
            targets.append([int(player_id[0]), int(player_id[1])])
        if len(targets) >= remaining:
            break
    return targets if len(targets) == remaining else []


def _chat_cooldown(context: dict[str, Any]) -> int:
    cooldowns = (context.get("runtime") or {}).get("cooldowns")
    if not isinstance(cooldowns, dict):
        return 0
    value = cooldowns.get("chat", 0)
    return int(value) if isinstance(value, int) else 0


def _is_target(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    )


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str = ""


class BedrockProviderError(RuntimeError):
    """Non-secret provider error safe to place in traces."""


def _invoke_bedrock_messages(
    provider: BedrockHaikuProvider,
    system_prompt: str,
    user_prompt: str,
) -> str:
    credentials = _resolve_aws_credentials()
    region = _aws_region()
    host = f"bedrock-runtime.{region}.amazonaws.com"
    model = str(provider.model)
    canonical_uri = f"/model/{quote(model, safe='-_.~')}/invoke"
    # Match AWS canonicalization: sign the single-encoded path, but let the
    # HTTP client send the raw model id. Sending `%3A` in the URL causes AWS to
    # canonicalize the percent again and reject the signature.
    url = f"https://{host}/model/{model}/invoke"
    payload = json.dumps(
        {
            "anthropic_version": BEDROCK_ANTHROPIC_VERSION,
            "max_tokens": int(provider.max_tokens or 512),
            "temperature": float(provider.temperature or 0.0),
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")

    headers = _sigv4_headers(
        credentials=credentials,
        region=region,
        host=host,
        canonical_uri=canonical_uri,
        payload=payload,
    )
    request = Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=float(provider.timeout_seconds or 12.0)) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        raise BedrockProviderError(detail) from exc
    except TimeoutError as exc:
        raise BedrockProviderError("Bedrock request timed out") from exc
    except URLError as exc:
        raise BedrockProviderError(_clip(f"Bedrock network error: {exc.reason}", 240)) from exc

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise BedrockProviderError("Bedrock returned invalid JSON") from exc
    return _claude_text(data)


def _sigv4_headers(
    *,
    credentials: AwsCredentials,
    region: str,
    host: str,
    canonical_uri: str,
    payload: bytes,
) -> dict[str, str]:
    payload_hash = hashlib.sha256(payload).hexdigest()
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    canonical_header_items = [
        ("accept", "application/json"),
        ("content-type", "application/json"),
        ("host", host),
        ("x-amz-content-sha256", payload_hash),
        ("x-amz-date", amz_date),
    ]
    if credentials.session_token:
        canonical_header_items.append(("x-amz-security-token", credentials.session_token))
    canonical_header_items.sort(key=lambda item: item[0])
    canonical_headers = "".join(f"{key}:{value}\n" for key, value in canonical_header_items)
    signed_headers = ";".join(key for key, _ in canonical_header_items)
    canonical_request = "\n".join(
        [
            "POST",
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{BEDROCK_SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _sigv4_signing_key(
        credentials.secret_access_key,
        date_stamp,
        region,
        BEDROCK_SERVICE,
    )
    signature = hmac.new(
        signing_key,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={credentials.access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Host": host,
        "X-Amz-Content-Sha256": payload_hash,
        "X-Amz-Date": amz_date,
        "Authorization": authorization,
    }
    if credentials.session_token:
        headers["X-Amz-Security-Token"] = credentials.session_token
    return headers


def _sigv4_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    key = ("AWS4" + secret_key).encode("utf-8")
    key = hmac.new(key, date_stamp.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, region.encode("utf-8"), hashlib.sha256).digest()
    key = hmac.new(key, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key, b"aws4_request", hashlib.sha256).digest()


def _resolve_aws_credentials() -> AwsCredentials:
    env_credentials = _credentials_from_env()
    if env_credentials is not None:
        return env_credentials

    container_credentials, container_detail = _credentials_from_container()
    if container_credentials is not None:
        return container_credentials

    cli_credentials, cli_detail = _credentials_from_aws_cli()
    if cli_credentials is not None:
        return cli_credentials

    raise BedrockProviderError(
        _clip(f"AWS credentials unavailable: {container_detail}; {cli_detail}", 240)
    )


def _credentials_from_env() -> AwsCredentials | None:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if not access_key or not secret_key:
        return None
    return AwsCredentials(
        access_key_id=access_key,
        secret_access_key=secret_key,
        session_token=os.environ.get("AWS_SESSION_TOKEN", "").strip(),
    )


def _credentials_from_container() -> tuple[AwsCredentials | None, str]:
    relative_uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").strip()
    full_uri = os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI", "").strip()
    if not relative_uri and not full_uri:
        return None, "container credentials env not set"

    url = full_uri or (AWS_CONTAINER_CREDENTIALS_ENDPOINT + relative_uri)
    headers: dict[str, str] = {}
    auth_token = os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN", "")
    auth_token_file = os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE", "")
    if auth_token:
        headers["Authorization"] = auth_token
    elif auth_token_file:
        try:
            headers["Authorization"] = Path(auth_token_file).read_text(encoding="utf-8").strip()
        except OSError:
            pass

    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=2.0) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return None, _clip(f"container credentials fetch failed: {type(exc).__name__}", 120)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, "container credentials JSON parse failed"

    access_key = str(data.get("AccessKeyId") or "").strip()
    secret_key = str(data.get("SecretAccessKey") or "").strip()
    if not access_key or not secret_key:
        return None, "container credentials missing access key fields"
    return (
        AwsCredentials(
            access_key_id=access_key,
            secret_access_key=secret_key,
            session_token=str(data.get("Token") or "").strip(),
        ),
        "",
    )


def _credentials_from_aws_cli() -> tuple[AwsCredentials | None, str]:
    if shutil.which("aws") is None:
        return None, "aws CLI not found"
    try:
        result = subprocess.run(
            ["aws", "configure", "export-credentials", "--format", "env-no-export"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
        )
    except Exception as exc:
        return None, _clip(f"aws credential export failed: {type(exc).__name__}", 120)
    if result.returncode != 0:
        return None, "aws credential export failed"

    values: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")

    access_key = values.get("AWS_ACCESS_KEY_ID", "")
    secret_key = values.get("AWS_SECRET_ACCESS_KEY", "")
    if not access_key or not secret_key:
        return None, "aws credential export missing access key fields"
    return (
        AwsCredentials(
            access_key_id=access_key,
            secret_access_key=secret_key,
            session_token=values.get("AWS_SESSION_TOKEN", ""),
        ),
        "",
    )


def _claude_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise BedrockProviderError("Bedrock response was not an object")
    content = data.get("content")
    if not isinstance(content, list):
        raise BedrockProviderError("Bedrock response missing content")
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise BedrockProviderError("Bedrock response had no text content")
    return "\n".join(parts)


def _http_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    message = ""
    try:
        data = json.loads(body) if body else {}
        if isinstance(data, dict):
            message = str(data.get("message") or data.get("Message") or "")
    except json.JSONDecodeError:
        message = body
    if "\n\nThe Canonical String" in message:
        message = message.split("\n\nThe Canonical String", 1)[0]
    detail = f"Bedrock HTTP {exc.code}"
    if message.strip():
        detail += ": " + message.strip()
    return _clip(detail, 240)


def _parse_decision_json(text: str) -> dict[str, Any] | None:
    stripped = _strip_code_fence(text.strip())
    for candidate in (stripped, _extract_json_object(stripped)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_provider_decision(decision: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(decision)
    rationale = normalized.get("rationale")
    if isinstance(rationale, str):
        normalized["rationale"] = _clip(rationale, 240)
    return normalized


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _bedrock_model() -> str:
    return _first_env(
        [
            "EURYDICE_LLM_MODEL",
            "EURYDICE_BEDROCK_MODEL",
            "COGAMES_LLM_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
            "ANTHROPIC_MODEL",
        ],
        DEFAULT_BEDROCK_HAIKU_MODEL,
    )


def _aws_region() -> str:
    return _first_env(
        [
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "AMAZON_BEDROCK_REGION",
            "BEDROCK_AWS_REGION",
        ],
        "us-east-1",
    )


def _first_env(names: list[str], default: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bounded_float(value: float, *, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


__all__ = [
    "BedrockHaikuProvider",
    "BedrockProviderError",
    "DEFAULT_BEDROCK_HAIKU_MODEL",
    "HeuristicProvider",
    "HoldProvider",
    "LLMProvider",
    "make_provider",
]
