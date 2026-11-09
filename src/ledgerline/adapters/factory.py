"""Pick the mock or the live client. Mock is the default."""

from __future__ import annotations

from ledgerline.adapters.live import LiveAirwallex
from ledgerline.adapters.mock import MockAirwallex
from ledgerline.clock import Clock
from ledgerline.config import Settings
from ledgerline.errors import LedgerlineError


def build_adapter(settings: Settings, clock: Clock) -> MockAirwallex | LiveAirwallex:
    if settings.mode == "live":
        if not settings.client_id or not settings.api_key:
            raise LedgerlineError(
                "config",
                "LEDGERLINE_MODE=live requires AIRWALLEX_CLIENT_ID and AIRWALLEX_API_KEY",
            )
        return LiveAirwallex(
            base_url=settings.base_url,
            client_id=settings.client_id,
            api_key=settings.api_key,
            clock=clock,
        )
    mock = MockAirwallex(clock)
    for currency, account_id in settings.global_accounts.items():
        if account_id:
            mock.register_global_account(account_id, currency)
    return mock
