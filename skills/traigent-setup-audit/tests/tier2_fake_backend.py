"""A fake Traigent backend on the loopback interface, for the Tier 2 tests.

Every payload here is either OBSERVED or LABELLED SYNTHETIC. The observed ones
are the shapes the live probe of the portal and the customer dogfood run
recorded on 2026-09-13 (`runs/setup-audit-2026-09-13/tier2-live-probe.md`, and
`experiments/ruler-dev-001/FINDINGS.md` §6-§7 in the customer project):

* evaluator quality ABSTAINS, with `anchor_type: none` and `evaluators: []`;
* example insights returns zero rows alongside `dataset_quality: low`;
* the example-scoring summary says `computed: false`;
* the example-scoring COMPUTE endpoint returns HTTP 500 — which is why this
  skill never calls it, and why the server keeps it wired as a 500 that no test
  is allowed to reach;
* a run id that is not a portal run id (a local `tv0_` session id, say) returns
  404 on every reader.

Nothing here is a happy path invented to make the relay look good. The single
synthetic payload — a `computed: true` summary — is marked as such below and
exists only to exercise the second read; no successful computation has ever been
observed on this account.

The server logs every request: method, full path, status, which header NAMES
arrived, and the User-Agent. The key's VALUE is absent from that log — only its
presence is noted — which is the discipline the script itself keeps.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Not a real credential: a low-entropy marker the tests plant in the environment
# and then grep for in every output.
SENTINEL_KEY = "traigent-setup-audit-sentinel-not-a-key"

RUN_ID = "a7db1575-4d8a-450e-84b1-c8c08627b19b"
EXPERIMENT_ID = "cbb7bf81-06cb-4677-aa82-19bf8627afab"
PROJECT_ID = "project_personal_66c1223ef6a64ce8a7cce5fbeb777479"
# A LOCAL session id. Not a portal run id; 404s on every analytics endpoint.
LOCAL_SESSION_ID = "tv0_local_session_0001"


def evaluator_quality(run_id: str) -> dict:
    """OBSERVED 2026-09-13: an abstain, with nothing assessed."""
    return {
        "success": True,
        "data": {
            "payload_version": "run_evaluator_quality.v1",
            "run_id": run_id,
            "status": "abstain",
            "reason": "audit_abstained",
            "anchor": {"anchor_type": "none"},
            "evaluators": [],
        },
    }


def example_insights(run_id: str) -> dict:
    """OBSERVED 2026-09-13: zero rows, `dataset_quality: low`."""
    return {
        "success": True,
        "data": {
            "run_id": run_id,
            "example_rows": [],
            "summary": {
                "dataset_quality": "low",
                "example_count": 0,
                "recommendation": "dataset_quality_unavailable",
            },
            "privacy_mode": "safe_agent_projection",
        },
    }


def decision_payload(run_id: str) -> dict:
    """OBSERVED 2026-09-13: run more trials, at `low` confidence."""
    return {
        "success": True,
        "data": {
            "run_id": run_id,
            "decision_brief": {
                "headline": "builder-haiku leads so far, but the sample is small",
                "confidence": "low",
                "recommended_action": {"kind": "rerun_larger_sample"},
                "evidence": {
                    "sample_size": "8 trial(s) over 18 distinct example(s)",
                    "project_usage": "$0.039432 across 70 configuration run(s)",
                },
                "drilldowns": ["analytics_get_run_leaderboard"],
                "warnings": [],
            },
        },
    }


def scoring_summary(computed: bool) -> dict:
    if not computed:
        # OBSERVED 2026-09-13.
        return {
            "success": True,
            "data": {
                "computed": False,
                "message": "Call POST /compute to trigger scoring",
            },
        }
    # SYNTHETIC. No successful computation has been observed for this account;
    # this exists only so the "results already exist" branch has a fixture.
    return {
        "success": True,
        "data": {"computed": True, "example_count": 18, "scored_example_count": 18},
    }


def dataset_quality(computed: bool) -> tuple[int, dict]:
    if not computed:
        # OBSERVED 2026-09-13: a 404 while nothing is computed.
        return 404, {
            "success": False,
            "error": {"message": "Quality scores not yet computed"},
        }
    # SYNTHETIC, for the same reason as the summary above.
    return 200, {
        "success": True,
        "data": {"dataset_quality": "low", "example_count": 18},
    }


# A hostile experiment id: the reply is the SERVER's text, and it becomes a URL
# path segment. Unquoted, this walked the next request out of the experiment-runs
# endpoint entirely.
HOSTILE_EXPERIMENT_ID = "../../../../api/v1/admin/secrets"


def experiments_page(count: int = 1, experiment_id: str = EXPERIMENT_ID) -> dict:
    return {
        "success": True,
        "data": {
            "experiments": [
                {
                    "experiment_id": experiment_id if index == 0
                    else f"{experiment_id}-{index}",
                    "project_id": PROJECT_ID,
                    "name": "ruler-dev-001",
                    "description": "text2sql grader development",
                }
                for index in range(count)
            ]
        },
    }


def experiment_runs(run_id: str) -> dict:
    return {
        "success": True,
        "data": {
            "runs": [
                {
                    "run_id": run_id,
                    "status": "completed",
                    "completed_at": "2026-09-13T09:12:00Z",
                    "description": "8 configuration runs",
                    "configuration_runs_count": 8,
                },
                {
                    "run_id": "00000000-0000-4000-8000-000000000002",
                    "status": "running",
                    "completed_at": None,
                    "description": "still going",
                    "configuration_runs_count": 2,
                },
            ]
        },
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # noqa: D401 - silence stderr noise
        return

    def do_GET(self) -> None:
        self._serve("GET")

    def do_POST(self) -> None:
        self._serve("POST")

    def _serve(self, method: str) -> None:
        route = self.path.split("?", 1)[0]
        backend = self.server.backend
        status, payload = backend.respond(method, route, self.headers)
        backend.log.append(
            {
                "method": method,
                "path": self.path,
                "route": route,
                "status": status,
                "header_names": sorted(name.lower() for name in self.headers),
                "user_agent": self.headers.get("User-Agent"),
                "has_api_key": self.headers.get("X-API-Key") is not None,
            }
        )
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeBackend:
    """A threaded loopback server implementing exactly the Tier 2 endpoints.

    ``computed`` switches the example-scoring summary to its SYNTHETIC
    "results exist" shape. ``run_id`` is the only run id the readers answer for:
    anything else 404s, the way a local session id does. ``experiments_in_reply``
    and ``experiment_id`` let a test answer a limit=10 page with 50 experiments,
    or with an id that tries to walk out of its endpoint.
    """

    def __init__(
        self,
        run_id: str = RUN_ID,
        computed: bool = False,
        experiments_in_reply: int = 1,
        experiment_id: str = EXPERIMENT_ID,
        forge: bool = False,
        bad_envelope: bool = False,
        error_status: int | None = None,
        echo_key_in_error: bool = False,
    ) -> None:
        self.run_id = run_id
        self.computed = computed
        self.experiments_in_reply = experiments_in_reply
        self.experiment_id = experiment_id
        self.forge = forge
        self.bad_envelope = bad_envelope
        self.error_status = error_status
        self.echo_key_in_error = echo_key_in_error
        self.log: list[dict] = []
        self.compute_calls = 0
        self._server = ThreadingHTTPServer(("localhost", 0), _Handler)
        self._server.backend = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "FakeBackend":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def paths(self) -> list[tuple[str, str]]:
        return [(row["method"], row["path"]) for row in self.log]

    # -- routing -----------------------------------------------------------

    def respond(self, method: str, route: str, headers) -> tuple[int, object]:
        if self.error_status is not None:
            body = {"success": False, "error": {"message": "upstream failure"}}
            if self.echo_key_in_error:
                body["error"]["request_headers"] = {
                    "X-API-Key": headers.get("X-API-Key")
                }
            return self.error_status, body
        if self.forge:
            # A 200 that is not the envelope: the relay must refuse to read it.
            return 200, b"<html><body>not the api you are looking for</body></html>"
        if self.bad_envelope:
            # Well-formed JSON, no `success`, and `data` is not an object. A
            # verdict read out of this would be invented.
            return 200, {"data": "status: excellent, evaluator: reliable"}

        parts = [part for part in route.strip("/").split("/") if part]
        if parts[:3] == ["api", "v1", "experiments"] and method == "GET":
            return 200, experiments_page(self.experiments_in_reply, self.experiment_id)
        if parts[:3] == ["api", "v1", "experiment-runs"] and parts[-1:] == ["runs"]:
            return 200, experiment_runs(self.run_id)
        if parts[:4] == ["api", "v1", "analytics", "runs"] and len(parts) == 6:
            if parts[4] != self.run_id:
                return 404, self._not_found()
            tail = parts[5]
            if tail == "evaluator-quality":
                return 200, evaluator_quality(parts[4])
            if tail == "example-insights":
                return 200, example_insights(parts[4])
            if tail == "decision-payload":
                return 200, decision_payload(parts[4])
        if parts[:4] == ["api", "v1", "analytics", "example-scoring"]:
            tail = parts[5] if len(parts) > 5 else ""
            if tail == "compute" and method == "POST":
                # OBSERVED 2026-09-13: HTTP 500. Wired here so a test can prove
                # the skill never reaches it, not so a test can use it.
                self.compute_calls += 1
                return 500, {"success": False,
                             "error": {"message": "internal server error"}}
            if parts[4] != self.run_id:
                return 404, self._not_found()
            if tail == "summary":
                return 200, scoring_summary(self.computed)
            if tail == "dataset-quality":
                return dataset_quality(self.computed)
        return 404, self._not_found()

    @staticmethod
    def _not_found() -> dict:
        return {"success": False,
                "error": {"code": "RESOURCE_NOT_FOUND", "message": "not found"}}
