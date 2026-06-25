from __future__ import annotations

from typing import Any


VLM_REQUEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "maker.vlm_request.v1",
    "title": "maker_v1 VLM Frame Request",
    "type": "object",
    "required": [
        "schema_version",
        "request_id",
        "guide_bundle_hash",
        "play_card_hash",
        "frame_id",
        "frame_hash",
        "run_id",
        "objective",
        "allowed_views",
        "allowed_actions",
        "recent_history",
        "parser_summary",
        "retrieved_context_ids",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": "maker.vlm_request.v1"},
        "request_id": {"type": "string", "minLength": 1},
        "guide_bundle_hash": {"type": "string", "minLength": 1},
        "play_card_hash": {"type": "string", "minLength": 1},
        "frame_id": {"type": "string", "minLength": 1},
        "frame_hash": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "objective": {"type": "string", "minLength": 1},
        "allowed_views": {"type": "array", "items": {"type": "string"}},
        "allowed_actions": {"type": "array", "items": {"type": "string"}},
        "recent_history": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["view", "action_id", "outcome"],
                "additionalProperties": False,
                "properties": {
                    "view": {"type": "string"},
                    "action_id": {"type": "string"},
                    "outcome": {"type": "string"},
                },
            },
        },
        "parser_summary": {"type": "object"},
        "retrieved_context_ids": {"type": "array", "items": {"type": "string"}},
    },
}


VLM_FRAME_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "maker.vlm_frame.v1",
    "title": "maker_v1 VLM Frame Response",
    "type": "object",
    "required": [
        "schema_version",
        "request_id",
        "frame_id",
        "view",
        "phase",
        "visible_text",
        "ui_elements",
        "entities",
        "state_observations",
        "available_actions",
        "recommended_action",
        "novelty",
        "parser_targets",
        "memory_updates",
        "uncertainty",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": "maker.vlm_frame.v1"},
        "request_id": {"type": "string", "minLength": 1},
        "frame_id": {"type": "string", "minLength": 1},
        "view": {"$ref": "#/$defs/classification"},
        "phase": {"$ref": "#/$defs/classification"},
        "visible_text": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "region", "confidence"],
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "region": {"$ref": "#/$defs/region"},
                    "confidence": {"$ref": "#/$defs/confidence"},
                },
            },
        },
        "ui_elements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "label", "region", "state", "confidence"],
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "enum": ["button", "menu", "cursor", "timer", "score", "chat", "label", "unknown"]
                    },
                    "label": {"type": "string"},
                    "region": {"$ref": "#/$defs/region"},
                    "state": {"enum": ["active", "inactive", "selected", "disabled", "unknown"]},
                    "confidence": {"$ref": "#/$defs/confidence"},
                },
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "label", "region", "attributes", "confidence"],
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "enum": [
                            "self",
                            "player",
                            "opponent",
                            "item",
                            "body",
                            "hazard",
                            "objective",
                            "unknown",
                        ]
                    },
                    "label": {"type": "string"},
                    "region": {"$ref": "#/$defs/region"},
                    "attributes": {"type": "object"},
                    "confidence": {"$ref": "#/$defs/confidence"},
                },
            },
        },
        "state_observations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "value", "status", "confidence", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": ["string", "number", "boolean", "null"]},
                    "status": {"enum": ["observed", "inferred", "guide_prior"]},
                    "confidence": {"$ref": "#/$defs/confidence"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "available_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["action_id", "confidence", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "action_id": {"type": "string"},
                    "confidence": {"$ref": "#/$defs/confidence"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "recommended_action": {
            "type": "object",
            "required": ["action_id", "parameters", "confidence", "rationale", "fallback_action_id"],
            "additionalProperties": False,
            "properties": {
                "action_id": {"type": "string"},
                "parameters": {"type": "object"},
                "confidence": {"$ref": "#/$defs/confidence"},
                "rationale": {"type": "string"},
                "fallback_action_id": {"type": "string"},
            },
        },
        "novelty": {
            "type": "object",
            "required": ["status", "save_frame", "reason"],
            "additionalProperties": False,
            "properties": {
                "status": {"enum": ["known", "variant", "new", "uncertain"]},
                "save_frame": {"type": "boolean"},
                "reason": {"type": "string"},
            },
        },
        "parser_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["target", "why", "suggested_test"],
                "additionalProperties": False,
                "properties": {
                    "target": {"type": "string"},
                    "why": {"type": "string"},
                    "suggested_test": {"type": "string"},
                },
            },
        },
        "memory_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "value", "status", "confidence", "evidence"],
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": ["string", "number", "boolean", "null"]},
                    "status": {"const": "candidate"},
                    "confidence": {"$ref": "#/$defs/confidence"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "uncertainty": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["field", "reason", "needed_next"],
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string"},
                    "reason": {"type": "string"},
                    "needed_next": {"type": "string"},
                },
            },
        },
    },
    "$defs": {
        "classification": {
            "type": "object",
            "required": ["id", "confidence", "evidence"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string"},
                "confidence": {"$ref": "#/$defs/confidence"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "region": {
            "type": "object",
            "required": ["x", "y", "w", "h"],
            "additionalProperties": False,
            "properties": {
                "x": {"type": "integer", "minimum": 0},
                "y": {"type": "integer", "minimum": 0},
                "w": {"type": "integer", "minimum": 0},
                "h": {"type": "integer", "minimum": 0},
            },
        },
    },
}
