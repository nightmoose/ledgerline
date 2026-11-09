"""Run the scripted demo. Mock mode is the default and does not call the network."""

from __future__ import annotations

import sys

from ledgerline import demo_run
from ledgerline.config import load_settings
from ledgerline.demo_run import run_demo
from ledgerline.service import Service


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    if settings.live and "--live" not in args:
        print("Refusing to run the demo against the live host without --live.")
        print("Leave LEDGERLINE_MODE=mock to run the full script with no credentials.")
        return 2
    service = Service(settings)
    demo_run.ECHO = True
    try:
        run_demo(service)
    except Exception as exc:
        print(f"Demo failed: {exc}")
        return 1
    finally:
        demo_run.ECHO = False
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
