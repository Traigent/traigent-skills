"""Bounded observations and failed reads cannot prove account-wide absence."""

import pytest
import tier2_checks as tier2


class Transport:
    api_key = "example_key"  # Offline fixture only; no request leaves this process.

    def __init__(self, experiments, responses=None, status=200):
        self.experiments = experiments
        self.responses = responses or {}
        self.status = status
        self.paths = []

    def request(self, method, path):
        self.paths.append(path)
        if path.startswith("/api/v1/experiments?"):
            status, data = self.status, {"experiments": self.experiments}
        else:
            key = path.split("/")[-2]
            status, data = self.responses.get(key, (200, {"runs": []}))
        return {"success": True, "data": data}, {
            "method": method, "path": path, "status": status,
            "response_bytes": 0, "elapsed_ms": 0,
        }


def inspect(transport):
    lines = []
    record = tier2.run_list_runs(transport, lines)
    text = "\n".join(lines)
    assert "No completed run exists on this account" not in text
    assert record["discovery"]["scope"] == "returned_pages"
    assert record["discovery"]["account_coverage"] == "not_verified"
    return record, text


@pytest.mark.parametrize("status,data", [(500, None), (200, None), (200, {}), (200, {"runs": [None]})])
def test_failed_or_unreadable_lookup_is_incomplete(status, data):
    transport = Transport([{"id": "a"}], {"a": (status, data)})
    record, text = inspect(transport)
    assert record["completed_runs"] == []
    assert record["discovery"]["complete"] is False
    assert record["discovery"]["failed_experiments"] == ["a"]
    assert "incomplete" in text and "retry" in text and "--run-id" in text


def test_mixed_lookup_keeps_completed_run_without_claiming_complete_discovery():
    transport = Transport([{"id": "a"}, {"id": "b"}], {
        "a": (200, {"runs": [{"run_id": "found", "status": "completed"}]}),
        "b": (500, None),
    })
    record, _ = inspect(transport)
    assert record["completed_runs"] == ["found"]
    assert record["discovery"]["complete"] is False


@pytest.mark.parametrize("count", [10, 13])
def test_full_or_oversized_page_keeps_request_bound_and_marks_partial(count):
    transport = Transport([{"id": str(i)} for i in range(count)])
    record, text = inspect(transport)
    assert len(transport.paths) == 11
    assert record["experiments_listed"] == 10
    assert record["discovery"]["experiment_page_full"] is True
    assert record["discovery"]["complete"] is False
    assert "inspected experiments" in text


def test_short_successful_page_records_only_returned_page_completeness():
    record, _ = inspect(Transport([{"id": "a"}]))
    assert record["discovery"]["complete"] is True
    assert record["discovery"]["failed_experiments"] == []


@pytest.mark.parametrize("status,experiments", [(500, []), (200, [None]), (200, [{}])])
def test_initial_failure_and_malformed_experiments_do_not_become_empty_accounts(status, experiments):
    record, _ = inspect(Transport(experiments, status=status))
    assert record["discovery"]["complete"] is False
    assert record["completed_runs"] == []
