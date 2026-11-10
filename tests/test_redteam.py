"""The hostile suite runs in CI: every case must be refused by code."""

from pathlib import Path

import pytest

import ledgerline.service as service_module
from ledgerline.redteam.cases import CASES, CLASSES, Case, _tool_case
from ledgerline.redteam.runner import run_all, summary_table


def test_every_hostile_case_is_refused_and_no_money_moves():
    results = run_all()
    assert 20 <= len(results) <= 30
    assert {item.klass for item in results} == set(CLASSES)
    not_refused = [(item.case_id, item.violations) for item in results if not item.refused]
    assert not_refused == []
    table = summary_table(results)
    assert f"**{len(results)} of {len(results)}**" in table
    assert table.rstrip().endswith("| **0** |")


def _case(case_id: str):
    return next(case for case in CASES if case.case_id == case_id)


def test_suite_catches_a_broken_approval_binding(monkeypatch, tmp_path: Path):
    # Mutation check: if approvals stopped binding to evidence, D1 must fail.
    monkeypatch.setattr(service_module, "bound_to", lambda approval, **current: approval.status == "approved")
    monkeypatch.setattr(service_module, "void_if_changed", lambda approval, **current: approval)
    case = _case("D1")
    result = case.run(tmp_path, case)
    assert result.refused is False
    assert any("money moved to obl_supplier" in item for item in result.violations)


def test_suite_catches_a_money_moving_tool(monkeypatch, tmp_path: Path):
    # Mutation check: if a tool could execute past the approval gate, the
    # same tool-call attack on the supplier conversion must be flagged.
    def leaky_dispatch(service, name, arguments=None):
        if name == "execute":
            return service.execute(arguments["obligation_id"])
        raise AssertionError("unexpected tool")

    monkeypatch.setattr(service_module, "dispatch", leaky_dispatch)
    monkeypatch.setattr(service_module.Service, "_require_bound", lambda self, line: None)
    case = Case("M1", "C", "mutant", "execute(obl_supplier)", _tool_case("execute", {"obligation_id": "obl_supplier"}))
    result = case.run(tmp_path, case)
    assert result.refused is False
    assert any("money moved to obl_supplier" in item for item in result.violations)


@pytest.mark.parametrize("case_id", ["E1", "E2"])
def test_suite_catches_a_missing_duplicate_lock(monkeypatch, tmp_path: Path, case_id: str):
    # Mutation check: no duplicate lock and a fresh request_id per call.
    counter = iter(range(1000))
    original_rid = service_module.Service._rid
    monkeypatch.setattr(service_module.Service, "_latest", lambda self, oid: None)
    monkeypatch.setattr(
        service_module.Service, "_rid", lambda self, *parts: original_rid(self, *parts, str(next(counter)))
    )
    case = _case(case_id)
    result = case.run(tmp_path, case)
    assert result.refused is False
    assert any("paid twice" in item for item in result.violations)
