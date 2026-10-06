"""Identity and failure controls for the read-only connected evidence path."""

import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "scripts" / "read_decision_brief.py"
spec = importlib.util.spec_from_file_location("decision_read", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def brief():
    return {"project_id": "project", "run_id": "run", "intent": "iterate",
            "headline": "More evidence needed", "confidence": "low",
            "recommended_action": {"kind": "run_more", "why": "Only one trial"},
            "evidence": [], "warnings": ["Unverified stability"], "drilldowns": [],
            "future_field": {"preserve": True}}


class Client:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def get_run_decision_brief(self, project_id, run_id, intent):
        self.calls.append((project_id, run_id, intent))
        if self.error:
            raise self.error
        return self.payload


def test_complete_low_confidence_brief_is_returned_unchanged():
    payload = brief()
    original = copy.deepcopy(payload)
    client = Client(payload)
    result = asyncio.run(module.read_decision_brief("project", "run", "iterate", client))
    assert json.loads(result) == original
    assert payload == original
    assert client.calls == [("project", "run", "iterate")]


@pytest.mark.parametrize("field,value", [("project_id", "other"), ("run_id", "invented"), ("intent", "deploy")])
def test_wrong_identity_is_refused(field, value):
    payload = brief()
    payload[field] = value
    with pytest.raises(ValueError, match="identity"):
        asyncio.run(module.read_decision_brief("project", "run", "iterate", Client(payload)))


@pytest.mark.parametrize("payload", [None, {"run_id": "run"}, {**brief(), "confidence": float("nan")}])
def test_incomplete_or_unserializable_evidence_is_refused(payload):
    with pytest.raises(ValueError):
        asyncio.run(module.read_decision_brief("project", "run", "iterate", Client(payload)))


def test_missing_or_unauthorized_run_has_no_fallback():
    client = Client(error=LookupError("missing run"))
    with pytest.raises(LookupError):
        asyncio.run(module.read_decision_brief("project", "run", "iterate", client))
    assert len(client.calls) == 1


def test_cli_failure_emits_no_payload_or_server_exception_text(monkeypatch, capsys):
    async def failed(args):
        raise RuntimeError("PRIVATE_TEST_RESPONSE")
    monkeypatch.setattr(module, "_read", failed)
    assert module.main(["--run-id", "run", "--project-id", "project"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "PRIVATE_TEST_RESPONSE" not in output.err
    assert "no run was verified" in output.err


@pytest.mark.parametrize("field,value", [("headline", None), ("headline", ""), ("confidence", "perfect"),
                                        ("confidence", []), ("recommended_action", None),
                                        ("recommended_action", {"kind": "wait"}),
                                        ("evidence", None), ("evidence", [{"type": "sample_size"}]),
                                        ("warnings", None), ("warnings", [None]),
                                        ("drilldowns", None), ("drilldowns", [{}])])
def test_malformed_visible_fields_are_not_verified(field, value):
    payload = brief()
    payload[field] = value
    with pytest.raises(ValueError):
        asyncio.run(module.read_decision_brief("project", "run", "iterate", Client(payload)))


@pytest.mark.parametrize("config_id", ["bad/id", "x" * 129, False])
def test_invalid_configuration_identity_is_refused(config_id):
    payload = brief()
    payload["recommended_action"]["config_id"] = config_id
    with pytest.raises(ValueError, match="configuration identity"):
        asyncio.run(module.read_decision_brief("project", "run", "iterate", Client(payload)))
