"""JSON helpers that keep money in Decimal and never emit binary floats."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


def to_plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return to_plain(value.model_dump())
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(to_plain(value), separators=(",", ":"), sort_keys=True)


def loads(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = raw
    return json.loads(text, parse_float=Decimal)


def wire_dumps(value: Any) -> str:
    """Encode Decimals as JSON numbers without passing through float."""
    plain = json.dumps(value, default=_decimal_token, separators=(",", ":"))
    return plain.replace('"__DEC__', "").replace('__DEC__"', "")


def _decimal_token(value: Any) -> str:
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".") or "0"
        return f"__DEC__{text}__DEC__"
    raise TypeError(f"cannot encode {type(value).__name__}")
