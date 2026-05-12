from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

ModelT = TypeVar("ModelT", bound=BaseModel)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def read_model(path: Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate(read_json(path))


def write_json(path: Path, payload: BaseModel | dict | list) -> None:
    path.write_text(json.dumps(to_jsonable_python(payload), indent=2) + "\n", encoding="utf-8")
