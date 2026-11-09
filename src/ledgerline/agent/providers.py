"""Optional Anthropic or xAI reader. Missing keys stay on the offline reader."""

from __future__ import annotations

import json
from typing import Any

import httpx

from ledgerline.agent.offline import read_evidence
from ledgerline.config import Settings

_SYSTEM = (
    "Read the treasury evidence. Reply with a JSON object with keys "
    "contradicts (boolean) and explanation (string). "
    "You cannot move money, change limits, or choose a payment action."
)


def build_reader(settings: Settings, transport: httpx.BaseTransport | None = None) -> EvidenceReader:
    provider = settings.model_provider
    if provider == "anthropic" and settings.anthropic_api_key and settings.model_name:
        return RemoteReader(
            provider="anthropic",
            url="https://api.anthropic.com/v1/messages",
            api_key=settings.anthropic_api_key,
            model=settings.model_name,
            transport=transport,
        )
    if provider == "xai" and settings.xai_api_key and settings.model_name:
        return RemoteReader(
            provider="xai",
            url="https://api.x.ai/v1/chat/completions",
            api_key=settings.xai_api_key,
            model=settings.model_name,
            transport=transport,
        )
    return OfflineReader()


class OfflineReader:
    provider = "offline"

    def interpret(self, text: str) -> dict[str, object]:
        return read_evidence(text)


class RemoteReader:
    def __init__(
        self,
        *,
        provider: str,
        url: str,
        api_key: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.url = url
        self.api_key = api_key
        self.model = model
        self._http = httpx.Client(transport=transport, timeout=30.0)

    def interpret(self, text: str) -> dict[str, object]:
        offline = read_evidence(text)
        try:
            raw = self._complete(text)
            parsed = parse_reading(raw)
        except (httpx.HTTPError, ValueError, KeyError):
            offline["fallback"] = "model call failed"
            return offline
        # The offline reader is a floor: a remote reading cannot raise confidence.
        contradicts = bool(offline["contradicts"] or parsed["contradicts"])
        explanation = str(parsed["explanation"] or offline["explanation"])
        return {
            "contradicts": contradicts,
            "explanation": explanation,
            "provider": self.provider,
        }

    def _complete(self, text: str) -> str:
        if self.provider == "anthropic":
            response = self._http.post(
                self.url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 400,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": text}],
                },
            )
            response.raise_for_status()
            body = response.json()
            return str(body["content"][0]["text"])
        response = self._http.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        return str(body["choices"][0]["message"]["content"])


class EvidenceReader:
    def interpret(self, text: str) -> dict[str, object]: ...


def parse_reading(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response did not contain JSON")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model response was not an object")
    # Action fields are ignored on purpose.
    return {
        "contradicts": bool(data.get("contradicts")),
        "explanation": str(data.get("explanation") or ""),
    }
