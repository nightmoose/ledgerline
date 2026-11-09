"""Runtime settings. Credentials are read from the environment and never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Login was observed to return 201 on both of these hosts.
DEMO_BASE_URL = "https://api-demo.airwallex.com"
SANDBOX_BASE_URL = "https://api.sandbox.airwallex.com"
ENV_BASE_URLS = {
    "demo": DEMO_BASE_URL,
    "sandbox": SANDBOX_BASE_URL,
}


def resolve_base_url(env: dict[str, str]) -> tuple[str, str]:
    """Return (base_url, airwallex_env).

    AIRWALLEX_BASE_URL wins when it is set. Otherwise AIRWALLEX_ENV selects a
    host: demo (default) or sandbox. Production is rejected.
    """
    airwallex_env = env.get("AIRWALLEX_ENV", "demo").strip().lower() or "demo"
    if airwallex_env == "production":
        raise ValueError("AIRWALLEX_ENV=production is not supported")
    explicit = env.get("AIRWALLEX_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/"), airwallex_env
    if airwallex_env not in ENV_BASE_URLS:
        known = ", ".join(sorted(ENV_BASE_URLS))
        raise ValueError(f"AIRWALLEX_ENV must be one of {known}, or set AIRWALLEX_BASE_URL")
    return ENV_BASE_URLS[airwallex_env], airwallex_env


def _find_limits(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"limits file not found: {path}")
        return path
    candidates = [
        Path.cwd() / "policy" / "limits.yaml",
        Path(__file__).resolve().parents[2] / "policy" / "limits.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("policy/limits.yaml not found; set LEDGERLINE_LIMITS")


@dataclass(frozen=True)
class Settings:
    mode: str
    base_url: str
    airwallex_env: str
    client_id: str
    api_key: str
    webhook_secret: str
    global_accounts: dict[str, str]
    model_provider: str
    model_name: str
    anthropic_api_key: str
    xai_api_key: str
    limits_path: Path
    data_dir: Path

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def audit_path(self) -> Path:
        return self.data_dir / "audit.jsonl"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ledgerline.sqlite3"


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    mode = env.get("LEDGERLINE_MODE", "mock").strip().lower() or "mock"
    if mode not in {"mock", "live"}:
        raise ValueError("LEDGERLINE_MODE must be mock or live")
    provider = env.get("LEDGERLINE_MODEL_PROVIDER", "offline").strip().lower() or "offline"
    if provider not in {"offline", "anthropic", "xai"}:
        raise ValueError("LEDGERLINE_MODEL_PROVIDER must be offline, anthropic, or xai")
    data_dir = Path(env.get("LEDGERLINE_DATA_DIR", "data"))
    if env.get("VERCEL") == "1" and "LEDGERLINE_DATA_DIR" not in env:
        data_dir = Path("/tmp/ledgerline")
    if mode == "mock":
        accounts = {
            "USD": env.get("AIRWALLEX_GLOBAL_ACCOUNT_USD") or "ga_usd_mock",
            "EUR": env.get("AIRWALLEX_GLOBAL_ACCOUNT_EUR") or "ga_eur_mock",
            "GBP": env.get("AIRWALLEX_GLOBAL_ACCOUNT_GBP") or "ga_gbp_mock",
        }
    else:
        accounts = {
            "USD": env.get("AIRWALLEX_GLOBAL_ACCOUNT_USD", ""),
            "EUR": env.get("AIRWALLEX_GLOBAL_ACCOUNT_EUR", ""),
            "GBP": env.get("AIRWALLEX_GLOBAL_ACCOUNT_GBP", ""),
        }
    secret = env.get("AIRWALLEX_WEBHOOK_SECRET", "")
    if mode == "mock" and not secret:
        secret = "ledgerline-mock-webhook-secret"
    base_url, airwallex_env = resolve_base_url(env)
    return Settings(
        mode=mode,
        base_url=base_url,
        airwallex_env=airwallex_env,
        client_id=env.get("AIRWALLEX_CLIENT_ID", ""),
        api_key=env.get("AIRWALLEX_API_KEY", ""),
        webhook_secret=secret,
        global_accounts=accounts,
        model_provider=provider,
        model_name=env.get("LEDGERLINE_MODEL", ""),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""),
        xai_api_key=env.get("XAI_API_KEY", ""),
        limits_path=_find_limits(env.get("LEDGERLINE_LIMITS")),
        data_dir=data_dir,
    )
