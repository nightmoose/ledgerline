from ledgerline.demo_run import run_demo


def test_scripted_demo_completes_in_mock_mode(service):
    report = run_demo(service)
    assert service.reserves_hold()
    assert any("DEFER → FUND" in line or "DEFER → FUND" in line for line in report.transcript)
    replay = service.replay()
    assert [event["seq"] for event in replay] == list(range(1, len(replay) + 1))
    assert replay[-1]["kind"] == "result"
