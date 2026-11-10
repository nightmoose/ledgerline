"""Treasury console. The process starts in mock mode unless LEDGERLINE_MODE=live."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ledgerline.config import Settings, load_settings
from ledgerline.demo_run import prepare_demo, run_demo, settle_demo
from ledgerline.fxmath import usd_eq
from ledgerline.live_evidence import load as load_live_evidence
from ledgerline.money import format_money
from ledgerline.redteam.cases import CLASSES
from ledgerline.redteam.runner import run_all
from ledgerline.service import Service

# Every interactive page says plainly whether it is the mock or the sandbox.
MOCK_BAR = "{page} · mock mode · synthetic data · no Airwallex calls"
LIVE_BAR = "{page} · live · Airwallex {env} sandbox"


def _bar(service: Service, page: str) -> str:
    if service.settings.live:
        return LIVE_BAR.format(page=page, env=service.settings.airwallex_env)
    return MOCK_BAR.format(page=page)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Ledgerline")
    app.state.settings = settings or load_settings()
    app.state.service = Service(app.state.settings)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        settings = app.state.settings
        return JSONResponse(
            {
                "mode": settings.mode,
                "base_url": settings.base_url,
                "airwallex_env": settings.airwallex_env,
            }
        )

    @app.get("/")
    def dashboard(request: Request, error: str = ""):
        return TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            _page(app.state.service, "dashboard", _bar(app.state.service, "treasury console"))
            | {"error": error},
        )

    @app.get("/trace")
    def trace(request: Request):
        service: Service = app.state.service
        events = []
        for event in service.replay():
            kind = str(event["kind"]).upper()
            klass = "ok" if kind in {"APPROVED", "WEBHOOK", "RESULT", "CONTRACT"} else ""
            if kind in {"POLICY", "GATE"}:
                klass = "warn"
            events.append(
                {
                    "time": str(event["ts"])[11:19],
                    "kind": kind,
                    "message": event["message"],
                    "klass": klass,
                    "hash": str(event.get("hash") or "")[:10],
                    "prev": str(event.get("prev_hash") or "")[:10],
                }
            )
        body = _page(service, "trace", _bar(app.state.service, "decision trace"))
        body.update({"events": events, "run_id": "run r_demo" if events else "", "chain": service.audit.verify()})
        return TEMPLATES.TemplateResponse(request, "trace.html", body)

    @app.get("/evidence")
    def evidence(request: Request):
        body = _page(app.state.service, "evidence", "recorded live sandbox run · Nov 9, 2026 · read-only")
        body.update({"live": load_live_evidence()})
        return TEMPLATES.TemplateResponse(request, "evidence.html", body)

    @app.get("/evidence.json")
    def evidence_json() -> JSONResponse:
        return JSONResponse(load_live_evidence())

    @app.get("/receipt")
    def receipt() -> JSONResponse:
        return JSONResponse(app.state.service.receipt())

    @app.get("/redteam")
    def redteam(request: Request):
        results = _redteam_results(app)
        body = _page(app.state.service, "redteam", _bar(app.state.service, "hostile test suite"))
        body.update(
            {
                "results": results,
                "groups": _redteam_groups(results),
                "refused": sum(1 for item in results if item.refused),
                "total": len(results),
            }
        )
        return TEMPLATES.TemplateResponse(request, "redteam.html", body)

    @app.get("/redteam.json")
    def redteam_json() -> JSONResponse:
        return JSONResponse([asdict(item) for item in _redteam_results(app)])

    @app.get("/policy")
    def policy(request: Request, error: str = ""):
        service: Service = app.state.service
        limits = service.limits
        floors = " / ".join(format_money(limits.reserve_floor[ccy]) for ccy in ("USD", "EUR", "GBP"))
        high = format_money(limits.fx_auto_limit_high_conf)
        low = format_money(limits.fx_auto_limit_low_conf)
        transfer_cap = format_money(limits.auto_transfer_limit)
        rules = [
            {"rule": "Reserve floor USD / EUR / GBP", "value": floors, "where": "policy.check_reserve()"},
            {"rule": "Auto FX limit at confidence ≥ 0.85", "value": f"{high} USD-eq", "where": "policy.fx_limit()"},
            {"rule": "Auto FX limit at confidence < 0.85", "value": f"{low} USD-eq", "where": "policy.fx_limit()"},
            {
                "rule": "Auto transfer limit",
                "value": f"{transfer_cap} USD-eq per payout",
                "where": "policy.transfer_limit()",
            },
            {
                "rule": "Beneficiary must be pre-verified",
                "value": str(limits.beneficiary_must_be_verified).lower(),
                "where": "executor.preflight()",
            },
            {
                "rule": "Max quote age before execute",
                "value": f"{limits.max_quote_age_seconds} s",
                "where": "executor.quote_fresh()",
            },
            {
                "rule": "Defer allowed if no penalty clause",
                "value": str(limits.defer_allowed_if_no_penalty).lower(),
                "where": "policy.can_defer()",
            },
        ]
        body = _page(service, "policy", _bar(app.state.service, "policy editor"))
        body.update(
            {
                "rules": rules,
                "version": limits.version,
                "preview": service.policy_preview,
                "draft_value": "2000",
                "error": error,
            }
        )
        return TEMPLATES.TemplateResponse(request, "policy.html", body)

    @app.post("/demo/prepare")
    def demo_prepare() -> RedirectResponse:
        return _swap(app, prepare_demo)

    @app.post("/demo/finish")
    def demo_finish() -> RedirectResponse:
        return _run(app, settle_demo)

    @app.post("/demo/run")
    def demo_run() -> RedirectResponse:
        return _swap(app, run_demo)

    @app.post("/approvals/{approval_id}/approve")
    def approve(approval_id: str, approver: str = Form("Alex")) -> RedirectResponse:
        return _run(app, lambda service: service.approve(approval_id, approver=approver))

    @app.post("/approvals/{approval_id}/reject")
    def reject(approval_id: str, approver: str = Form("Alex")) -> RedirectResponse:
        return _run(app, lambda service: service.reject(approval_id, approver=approver))

    @app.post("/policy/preview")
    def policy_preview(fx_auto_limit_low_conf: str = Form(...)) -> RedirectResponse:
        return _run(
            app,
            lambda service: service.preview_limit("fx_auto_limit_low_conf", fx_auto_limit_low_conf),
            target="/policy",
        )

    @app.post("/policy/approve")
    def policy_approve() -> RedirectResponse:
        return _run(app, lambda service: service.apply_draft(), target="/policy")

    @app.post("/policy/discard")
    def policy_discard() -> RedirectResponse:
        return _run(app, lambda service: service.discard_draft(), target="/policy")

    @app.post("/webhooks/airwallex")
    async def webhooks(request: Request) -> Response:
        raw = await request.body()
        result = app.state.service.receive_webhook(
            raw,
            request.headers.get("x-timestamp", ""),
            request.headers.get("x-signature", ""),
            now_ms=int(time.time() * 1000),
        )
        # One line per delivery for the host's request log. No secrets, no body.
        name = transfer_id = transfer_status = None
        if result["status"] == 200:
            event = json.loads(raw)
            data = event.get("data") or {}
            obj = data.get("object") if isinstance(data.get("object"), dict) else data
            name = event.get("name")
            transfer_id = obj.get("id")
            transfer_status = obj.get("status")
        print(
            "webhook",
            json.dumps(
                {
                    "status": result["status"],
                    "code": result.get("code"),
                    "event_id": result.get("event_id"),
                    "name": name,
                    "transfer_id": transfer_id,
                    "transfer_status": transfer_status,
                    "duplicate": result.get("duplicate"),
                }
            ),
            flush=True,
        )
        return Response(status_code=int(result["status"]))

    return app


def _swap(app: FastAPI, runner) -> RedirectResponse:
    # Each console run gets its own audit log, so the trace and its hash-chain
    # receipt cover exactly one run.
    base: Settings = app.state.settings
    run_dir = base.data_dir / "runs" / uuid.uuid4().hex[:8]
    try:
        fresh = Service(replace(base, data_dir=run_dir))
        runner(fresh)
    except Exception as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
    previous = app.state.service
    app.state.service = fresh
    previous.close()
    if previous.settings.data_dir.parent == base.data_dir / "runs":
        shutil.rmtree(previous.settings.data_dir, ignore_errors=True)
    return RedirectResponse("/", status_code=303)


def _redteam_results(app: FastAPI):
    cached = getattr(app.state, "redteam", None)
    if cached is None:
        cached = run_all()
        app.state.redteam = cached
    return cached


def _redteam_groups(results) -> list[dict]:
    groups = []
    for key, label in CLASSES.items():
        items = [item for item in results if item.klass == key]
        groups.append(
            {"label": label, "attempts": len(items), "refused": sum(1 for item in items if item.refused)}
        )
    return groups


def _run(app: FastAPI, runner, target: str = "/") -> RedirectResponse:
    try:
        runner(app.state.service)
    except Exception as exc:
        return RedirectResponse(f"{target}?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(target, status_code=303)


def _page(service: Service, page: str, bar: str) -> dict:
    balances = service.wallet()
    limits = service.limits
    cards = []
    for currency in ("USD", "EUR", "GBP"):
        cards.append(
            {
                "label": f"{currency} available",
                "value": format_money(balances.get(currency, 0)),
                "detail": f"reserve floor {format_money(limits.reserve_floor[currency])}",
                "klass": "",
            }
        )
    due = Decimal("0")
    shortfall = Decimal("0")
    lines = []
    obligations = {item.id: item for item in service.obligations}
    if service.plan:
        for line in service.plan.lines:
            due += usd_eq(line.amount, line.currency, limits.indicative_eur_per_usd, limits.indicative_usd_per_gbp)
            if line.action in {"DEFER", "ESCALATE"}:
                shortfall += usd_eq(
                    line.amount, line.currency, limits.indicative_eur_per_usd, limits.indicative_usd_per_gbp
                )
            lines.append(_line_view(service, line, obligations.get(line.obligation_id)))
    cards.append(
        {
            "label": "Due next 72h",
            "value": format_money(due),
            "detail": f"{len(service.obligations)} obligations · shortfall {format_money(shortfall)} USD-eq",
            "klass": "warn" if shortfall else "",
        }
    )
    title = "Ledgerline"
    plan_title = "No plan yet"
    if service.plan:
        plan_title = f"Proposed actions (plan v{service.plan.version})"
        if service.last_diff.changes:
            plan_title += " — replanned after deposit"
    mode = service.settings.mode
    host = "demo host" if "api-demo" in service.settings.base_url else service.settings.airwallex_env
    return {
        "title": title,
        "bar": bar,
        "page": page,
        "cards": cards,
        "lines": lines,
        "plan_title": plan_title,
        "confidence": f"{service.confidence}",
        "mode_label": f"{mode} · {host}",
        "live_mode": service.settings.live,
        "error": "",
        "events": [],
        "run_id": "",
        "rules": [],
        "version": limits.version,
        "preview": None,
        "draft_value": "2000",
    }


def _line_view(service: Service, line, obligation) -> dict:
    label = obligation.label if obligation and obligation.label else line.counterparty
    if line.action == "CONVERT-MIN":
        amount = (
            f"USD→{line.currency} {format_money(line.amount)} "
            f"(incl. {line.fee_currency} {format_money(line.fee_amount)} SWIFT fee)"
        )
    elif line.action == "DEFER":
        amount = "—"
    else:
        amount = f"{line.currency} {format_money(line.amount)} {line.method}"
    checks = []
    check_class = "ok"
    for check in line.checks:
        mark = "✓" if check.ok else "✗"
        checks.append(f"{mark} {check.detail}")
        if not check.ok:
            check_class = "bad"
    approval = service._approval_for(line.obligation_id)
    kind = "text"
    decision = line.status
    klass = ""
    approve_label = "Approve"
    if line.action == "DEFER":
        decision = "Deferred"
        klass = "warn"
    elif approval and approval.status == "pending":
        kind = "approval"
        approve_label = "Approve exception" if line.action == "ESCALATE" else "Approve"
    elif approval and approval.status == "approved" and line.status not in {"paid", "in_flight", "cancelled"}:
        decision = "Approved"
        klass = "ok"
    elif line.status == "paid":
        latest = service._latest(line.obligation_id)
        if latest is not None and latest.attempt > 1:
            decision = "Replaced · PAID"
        elif line.auto_execute or line.action == "FUND":
            decision = "Auto-executed · PAID"
        else:
            decision = "PAID"
        klass = "ok"
    elif line.status == "in_flight":
        latest = service._latest(line.obligation_id)
        transfer_status = "SENT"
        if latest is not None:
            transfer_status = str(service.adapter.get_transfer(latest.transfer_id)["status"])
        decision = transfer_status
        klass = "warn" if transfer_status == "SENT" else "ok"
    elif line.status == "cancelled":
        decision = "CANCELLED"
        klass = "bad"
    elif line.action == "ESCALATE":
        decision = "Needs exception"
        klass = "bad"
    elif line.auto_execute:
        decision = "Ready · auto"
        klass = "ok"
    return {
        "action": line.action,
        "label": label,
        "amount": amount,
        "reason": line.reason,
        "checks": checks,
        "check_class": check_class,
        "kind": kind,
        "decision": decision,
        "klass": klass,
        "approval_id": approval.id if approval else "",
        "approve_label": approve_label,
    }


app = create_app()
