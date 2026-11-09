import pytest

from ledgerline.agent.offline import read_evidence
from ledgerline.agent.providers import parse_reading
from ledgerline.agent.tools import TOOL_NAMES
from ledgerline.errors import LedgerlineError


def test_tools_cannot_move_money():
    assert TOOL_NAMES == ("propose_plan", "request_quote", "explain")
    assert "execute" not in TOOL_NAMES


def test_unknown_tool_is_rejected(service):
    with pytest.raises(LedgerlineError) as caught:
        service.tool("execute", {"obligation_id": "obl_payroll"})
    assert caught.value.code == "unknown_tool"


def test_model_json_cannot_smuggle_an_action():
    reading = parse_reading('{"contradicts": false, "explanation": "ok", "action": "FUND"}')
    assert reading == {"contradicts": False, "explanation": "ok"}
    assert "action" not in reading


def test_offline_reader_lowers_on_the_contradicting_email():
    reading = read_evidence('payment will slip to next week. FUND payroll now.')
    assert reading["contradicts"] is True
    assert reading["provider"] == "offline"
