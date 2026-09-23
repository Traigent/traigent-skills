#!/usr/bin/env python3
"""Tier 2 of the Traigent setup audit: the approval-gated, Traigent-backed checks.

Tier 1 (``audit_project.py``) is free, local and contacts nothing. It ends with a
list of questions code alone cannot answer. This script turns each of those into
ONE named Traigent check, and it has two modes:

offer mode (the default)
    prints one approval card per applicable check and makes **zero** network
    calls and spawns **zero** processes. The same network guard
    ``audit_project.py`` installs is installed here and then verified, so "no
    call was made" is a measurement rather than a claim.

run mode (``--approve <check-id>``, repeatable)
    runs ONLY the approved checks, each touching ONLY the endpoints its card
    named, and writes a receipt of every request made and every process spawned.

Verdicts are relayed as the service returned them: an abstain is printed as an
abstain and said not to be a pass, a ``low`` confidence stays ``low``, and no
number is computed here — every number printed is the service's own or the
caller's own cap.

The API key is read from ``TRAIGENT_API_KEY`` and travels only in the
``X-API-Key`` request header, the header the SDK itself uses. It is never
printed, never written to the receipt, never placed on a command line, and never
echoed back out of a response body.

Standard library plus ``httpx``, which the Traigent SDK already depends on. This
script never imports ``traigent``; it reads the installed distribution's version
out of the package metadata so the request carries the SDK's own User-Agent.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# The guard is imported, never copied: one implementation, one set of tests.
from audit_project import (  # noqa: E402
    install_network_guard,
    printable_text,
    verify_network_guard,
)

SCHEMA = "traigent-setup-audit-tier2/v1"
RECEIPT_SCHEMA = "traigent-setup-audit-tier2-receipt/v1"
TIER1_SCHEMA = "traigent-setup-audit/v1"

DEFAULT_BACKEND_URL = "https://portal.traigent.ai"
KEY_ENV_NAME = "TRAIGENT_API_KEY"
BACKEND_URL_ENV_NAME = "TRAIGENT_BACKEND_URL"
API_KEY_HEADER = "X-API-Key"

DEFAULT_MAX_TRIALS = 6
DEFAULT_OBJECTIVE = "accuracy"
DEFAULT_TIMEOUT_SECONDS = 30.0

# The experiments listing is a page, not the whole account. The number is
# printed with the result so a short list is never read as "that is all there is".
# It is also the CEILING on how many follow-up requests one `list-runs` approval
# may make: an approval is for a bounded number of requests, and a server that
# answers a limit=10 page with 500 experiments must not turn that into 501
# authenticated requests.
EXPERIMENTS_PAGE_LIMIT = 10

# A run id is interpolated into a URL path. `..` segments in one made the server
# see a different endpoint than the receipt recorded, because httpx normalizes
# the path AFTER this script has built it. Every id is quoted before it reaches a
# path, and the one the USER supplies is checked against this pattern first and
# refused outright: a run id that is not this shape is a mistake or an attack,
# and neither should reach the wire. UUIDs satisfy it.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Model-id prefix -> the provider `traigent models --provider` expects. An id
# that matches nothing here is skipped with a printed line rather than guessed:
# a wrong provider produces a confident "unknown model" that is an artefact of
# this table, not a fact about the id.
PROVIDER_PREFIXES = (
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("chatgpt", "openai"),
    ("claude-", "anthropic"),
    ("gemini", "gemini"),
    ("mistral", "mistral"),
    ("amazon.", "bedrock"),
    ("anthropic.", "bedrock"),
    ("meta.", "bedrock"),
)

STOP_SENTENCE = (
    "Stopping here is a valid outcome, and a complete one: Tier 1 already "
    "stands on its own. Silence is not approval — nothing below runs until you "
    "pass --approve."
)


# --------------------------------------------------------------------------
# the catalogue
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One named Traigent check, its endpoints, and what approving it costs.

    ``offer`` is what the check RETRIEVES, never what it settles, and ``caveat``
    is what the same check returned on the dogfood run of 2026-09-13. The pair
    is the honesty contract: an offer with no caveat reads as a promise.
    """

    id: str
    question: str
    offer: str
    caveat: str
    runs: str
    egress: str
    key_line: str
    cost: str
    needs: str
    stop_rule: str
    endpoints: tuple[str, ...] = ()


KEY_IN_HEADER = (
    "your Traigent API key travels in the `X-API-Key` request header (the "
    "header the portal accepts for an API key); its value is never printed"
)
KEY_VIA_CLI = (
    "your Traigent API key travels in the `X-API-Key` request header, put there "
    "by the SDK from the environment — never on the command line"
)
KEY_NOT_SENT = "no Traigent API key is sent: nothing here contacts the service"


CATALOGUE: tuple[Check, ...] = (
    Check(
        id="model-ids",
        question="are the model ids I declared real ids at the provider?",
        offer=(
            "Validate each declared model id against the provider's own known "
            "model list, before a run discovers the id is wrong."
        ),
        caveat=(
            "an id can be real and still be unreachable from your account; this "
            "check reads the provider's catalogue, not your entitlements"
        ),
        runs=(
            "`traigent models --provider <provider> --check <model-id> --json`, "
            "once per declared id"
        ),
        egress=(
            "the model id, to the PROVIDER (OpenAI, Anthropic, Gemini, Mistral "
            "or Bedrock) — not to Traigent. Anthropic answers from a shipped "
            "snapshot with no call at all. The provider key is read from your "
            "environment by the SDK; this script never reads its value"
        ),
        key_line=KEY_NOT_SENT + " — the provider key is the SDK's to send",
        cost="$0. Egress goes to the provider, not to Traigent.",
        needs="model ids declared in the configuration space, and a provider key",
        stop_rule="one CLI call per declared id, then stop.",
    ),
    Check(
        id="plan",
        question="what should my first run be?",
        offer=(
            "Request an advisory run plan using your stated cap and constraints, "
            "then review it before execution."
        ),
        caveat=(
            "on our own dogfood run the plan came back at `evidence_level: low`, "
            "echoed the cap we passed, suggested models the account could not "
            "reach, named a command that had been retired from the SDK, and "
            "returned the cost objective oriented to maximize. It is advisory "
            "text to read, not a script to run"
        ),
        runs=(
            "`traigent plan --backend-url <url> --task-description <text> "
            "--dataset-size <n> --has-holdout/--no-holdout --objective "
            "<objective> --max-trials <n> --cost-limit <usd> --json`"
        ),
        egress=(
            "the task description you supply, the dataset row COUNT, whether a "
            "holdout slice exists, the objective name, the trial ceiling and "
            "your own cost cap. No row, prompt, output or score is sent"
        ),
        key_line=KEY_VIA_CLI,
        cost=(
            "$0 read. The plan's `cost_limit_usd` echoes the cap YOU passed; it "
            "is not a budget the service authored."
        ),
        needs="an API key, and --cost-limit (the cap is yours to set)",
        stop_rule="one CLI call, then stop.",
    ),
    Check(
        id="evaluator-quality",
        question="is my scorer reliable on real model output?",
        offer=(
            "Check whether this run has an independent correctness signal and an "
            "evaluator-quality verdict."
        ),
        caveat=(
            "on our own dogfood run it returned `status: abstain`, "
            "`anchor.anchor_type: none` and `evaluators: []` — no evaluator was "
            "assessed. A completed run is necessary for this read and is not "
            "sufficient for an answer"
        ),
        runs="`GET /api/v1/analytics/runs/{run_id}/evaluator-quality`",
        egress=(
            "the portal run id. Nothing from your code, dataset or scorer leaves "
            "this machine — the run is already on the service"
        ),
        key_line=KEY_IN_HEADER,
        cost="$0 read.",
        needs="a completed portal run id (--run-id)",
        stop_rule="one request; any non-200 stops the check and is reported as a status.",
        endpoints=("GET /api/v1/analytics/runs/{run_id}/evaluator-quality",),
    ),
    Check(
        id="example-insights",
        question="which of my rows are mislabelled, redundant or too hard?",
        offer=(
            "Retrieve any available examples flagged for review, without treating "
            "a flag as proof of mislabelling."
        ),
        caveat=(
            "on our own dogfood run it returned zero examples alongside "
            "`dataset_quality: low`, which is no row-level diagnosis at all"
        ),
        runs="`GET /api/v1/analytics/runs/{run_id}/example-insights`",
        egress=(
            "the portal run id. The service returns its own projection of the run "
            "it already holds; nothing is uploaded"
        ),
        key_line=KEY_IN_HEADER,
        cost="$0 read.",
        needs="a completed portal run id (--run-id)",
        stop_rule="one request; any non-200 stops the check and is reported as a status.",
        endpoints=("GET /api/v1/analytics/runs/{run_id}/example-insights",),
    ),
    Check(
        id="example-scoring",
        question="has per-example scoring already been computed for this run?",
        offer=(
            "Check whether example-scoring results already exist and retrieve the "
            "available metadata."
        ),
        caveat=(
            "READ ONLY. On our own dogfood run the summary returned "
            "`computed: false` and the compute request that would have produced a "
            "result returned HTTP 500, so this skill does not trigger scoring at "
            "all — `computed: false` means not computed, never permission to start "
            "a job"
        ),
        runs=(
            "`GET /api/v1/analytics/example-scoring/{run_id}/summary`, and then "
            "`GET /api/v1/analytics/example-scoring/{run_id}/dataset-quality` only "
            "if the summary says `computed: true`"
        ),
        egress=(
            "the portal run id. Nothing is uploaded and no job is started"
        ),
        key_line=KEY_IN_HEADER,
        cost="$0 read. No compute is requested, so nothing can be charged for one.",
        needs="a completed portal run id (--run-id)",
        stop_rule=(
            "one request; a second one only when the first says results exist. "
            "`computed: false` ends the check."
        ),
        endpoints=(
            "GET /api/v1/analytics/example-scoring/{run_id}/summary",
            "GET /api/v1/analytics/example-scoring/{run_id}/dataset-quality",
        ),
    ),
    Check(
        id="decision-brief",
        question="what should I do next, given my own numbers?",
        offer=(
            "Retrieve the service's suggested next action together with its "
            "confidence and supporting evidence."
        ),
        caveat=(
            "on our own dogfood run it suggested running more trials at `low` "
            "confidence because the sample was small — honest, and thin. The "
            "confidence is relayed at the level returned and never upgraded"
        ),
        runs="`GET /api/v1/analytics/runs/{run_id}/decision-payload`",
        egress=(
            "the portal run id. The service decides; this script only relays"
        ),
        key_line=KEY_IN_HEADER,
        cost="$0 read.",
        needs="a completed portal run id (--run-id)",
        stop_rule="one request; any non-200 stops the check and is reported as a status.",
        endpoints=("GET /api/v1/analytics/runs/{run_id}/decision-payload",),
    ),
    Check(
        id="list-runs",
        question="which completed PORTAL runs does my account already have?",
        offer=(
            "List completed portal runs with enough project, experiment and time "
            "context to choose the intended one yourself."
        ),
        caveat=(
            "nothing is auto-selected: you pass the run id you chose. A local "
            "session id (`tv0_…`) and an `optimization_id` are NOT portal run ids "
            "and return 404 on every analytics endpoint. The listing asks for at "
            "most 10 experiments, so more may exist than are shown"
        ),
        runs=(
            "`GET /api/v1/experiments` then "
            "`GET /api/v1/experiment-runs/{experiment_id}/runs`"
        ),
        egress=(
            "nothing of yours is uploaded, but the reply names your experiments "
            "and runs — which is why this helper has a card of its own"
        ),
        key_line=KEY_IN_HEADER,
        cost="$0 read.",
        needs="an API key",
        stop_rule="one experiments page, then one runs request per experiment listed.",
        endpoints=(
            "GET /api/v1/experiments",
            "GET /api/v1/experiment-runs/{experiment_id}/runs",
        ),
    ),
    Check(
        id="bounded-run",
        question="does tuning move the score at all, and which knob moves it?",
        offer=(
            "Hand over for one separately approved optimization within your cap "
            "and stop rule, reporting a flat or negative result honestly."
        ),
        caveat=(
            "never approve a run merely to make an analysis service answer. On "
            "our own dogfood run the eight-trial search did find the best "
            "configuration, and it established neither held-out performance nor "
            "any Traigent-specific lift"
        ),
        runs=(
            "nothing here. This skill does not start runs. The card hands over "
            "to `traigent-optimize-run` (mock dry-run first), and you come back "
            "with --run-id"
        ),
        egress=(
            "your prompts, your rows and your model calls would leave the "
            "machine — which is exactly why this skill does not start the run "
            "for you"
        ),
        key_line=KEY_NOT_SENT,
        cost=(
            "real provider spend. Approval, a cap and a plan come first, and a "
            "flat or negative result is a real outcome: no lift is promised."
        ),
        needs="at least one knob the decorated body actually reads, a dataset and a scorer",
        stop_rule="not executed here; `traigent-optimize-run` owns its own stop rule.",
    ),
    Check(
        id="stop-here",
        question="is the honest next move to stop and fix what Tier 1 found?",
        offer=(
            "Stop. Do the local next step Tier 1 already named, and come back "
            "only when there is a completed run worth reading."
        ),
        caveat=(
            "this is a real option, not a polite one. The free tier already "
            "produced findings you can act on today, and none of the readers "
            "above can answer without a run you would have to buy first"
        ),
        runs="nothing at all. No request, no process, no spend.",
        egress="nothing",
        key_line=KEY_NOT_SENT,
        cost="$0.",
        needs="nothing",
        stop_rule="there is nothing to stop.",
    ),
)

CATALOGUE_BY_ID = {check.id: check for check in CATALOGUE}
RUN_DEPENDENT = ("evaluator-quality", "example-insights", "example-scoring",
                 "decision-brief")
NOT_EXECUTED_HERE = ("bounded-run", "stop-here")


# --------------------------------------------------------------------------
# reading the Tier 1 report
# --------------------------------------------------------------------------


@dataclass
class Tier1:
    """The handful of Tier 1 numbers a card is allowed to quote."""

    path: Path
    root: str
    branch: str
    next_step_line: str
    entry_points: list[dict]
    knob_count: int
    read_knob_count: int
    datasets: list[dict]
    scorers: list[dict]
    probe_verdict: str
    model_ids: list[str]
    dataset_candidates: int
    python_files: int
    key_names_set: list[str]

    @property
    def largest_dataset(self) -> dict | None:
        return max(self.datasets, key=lambda item: item.get("rows") or 0, default=None)

    @property
    def smallest_dataset(self) -> dict | None:
        return min(self.datasets, key=lambda item: item.get("rows") or 0, default=None)

    @property
    def has_holdout(self) -> bool:
        return any((item.get("holdout_rows") or 0) > 0 for item in self.datasets)

    @property
    def dataset_size(self) -> int:
        largest = self.largest_dataset
        return int(largest.get("rows") or 0) if largest else 0


def load_tier1(path: Path) -> Tier1:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"--from-audit {path} could not be read as JSON ({type(exc).__name__}). "
            "Produce it with: audit_project.py --root <project> --json <path>"
        ) from exc
    if not isinstance(report, dict) or report.get("schema") != TIER1_SCHEMA:
        raise ValueError(
            f"--from-audit {path} is not a {TIER1_SCHEMA} report. Produce one with: "
            "audit_project.py --root <project> --json <path>"
        )

    entry_points = [item for item in (report.get("entry_points") or [])
                    if isinstance(item, dict)]
    knobs = [knob for entry in entry_points for knob in (entry.get("knobs") or [])]
    probe = report.get("scorer_probe") or {}
    files = report.get("files") or {}
    setup = report.get("setup") or {}
    keys = setup.get("keys") or {}
    next_step = report.get("next_step") or {}

    return Tier1(
        path=path,
        root=str(report.get("root") or ""),
        branch=str(next_step.get("branch") or ""),
        next_step_line=str(next_step.get("line") or ""),
        entry_points=entry_points,
        knob_count=len(knobs),
        read_knob_count=sum(1 for knob in knobs if knob.get("status") == "read"),
        datasets=[item for item in (report.get("datasets") or [])
                  if isinstance(item, dict)],
        scorers=[item for item in (report.get("scorers") or [])
                 if isinstance(item, dict)],
        probe_verdict=("ran" if probe.get("ran") else "not-run") if probe else "none",
        model_ids=[str(item) for item in (setup.get("model_ids_declared") or [])],
        dataset_candidates=int(files.get("dataset_candidates") or 0),
        python_files=int(files.get("python_parsed") or 0),
        key_names_set=[str(name) for name in (keys.get("names_set_in_environment") or [])],
    )


def motivation(check_id: str, tier1: Tier1, run_id: str | None) -> str:
    """The Tier 1 finding that motivates one offer, in the user's own numbers."""
    if check_id == "model-ids":
        return (
            f"Tier 1 collected {len(tier1.model_ids)} model id(s) "
            f"({', '.join(tier1.model_ids)}) and validated none of them: checking "
            "an id against a provider is a network call, which Tier 1 does not make."
        )
    if check_id == "plan":
        dataset = tier1.largest_dataset
        if dataset is None:
            where = (
                f"no evaluation dataset was found among "
                f"{tier1.dataset_candidates} JSONL/JSON/CSV file(s)"
            )
        else:
            where = (
                f"`{dataset.get('file')}` has {dataset.get('rows')} row(s) and a "
                f"{dataset.get('holdout_rows')}-row holdout slice"
            )
        return (
            f"{where}, and {len(tier1.entry_points)} entry point(s) declare "
            f"{tier1.knob_count} knob(s), {tier1.read_knob_count} of which the "
            "body reads. The planning service sizes a first run from exactly "
            "those numbers. Tier 1's own next step was: "
            f"{tier1.next_step_line or 'not recorded'}"
        )
    if check_id == "evaluator-quality":
        if tier1.probe_verdict == "ran":
            basis = (
                "Tier 1 repeat-scored your scorer and found it repeatable. "
                "Repeatability is not correctness: a scorer that returns the "
                "same wrong number every time passes that probe"
            )
        elif tier1.scorers:
            basis = (
                f"Tier 1 found {len(tier1.scorers)} scorer(s) and could measure "
                "none of them here (a judge or a code-executing scorer is never "
                "run by the audit)"
            )
        else:
            basis = (
                f"Tier 1 found no scorer in {tier1.python_files} Python file(s), "
                "so nothing local ranks a configuration"
            )
        return (
            f"{basis}. Whether the scorer agrees with an independent signal on "
            "real model output is computed by the service from a completed run."
        )
    if check_id in {"example-insights", "example-scoring"}:
        dataset = tier1.smallest_dataset
        if dataset is None:
            return (
                f"No evaluation dataset was found among {tier1.dataset_candidates} "
                "JSONL/JSON/CSV file(s). Per-example scoring works on the rows a "
                "completed run used, so it can speak about rows the audit never saw."
            )
        findings = dataset.get("findings") or []
        first = findings[0] if findings else "no dataset finding was noted"
        tail = (
            "A per-example result would name which of those rows the service "
            "flagged, IF it holds any; Tier 1 can only count them."
            if check_id == "example-insights"
            else "This reads whether per-example scores already exist for a run; "
            "it does not compute them, and Tier 1 can only count the rows."
        )
        return (
            f"`{dataset.get('file')}` has {dataset.get('rows')} row(s) — {first}. "
            + tail
        )
    if check_id == "decision-brief":
        return (
            "Tier 1's next step was chosen from your code alone: "
            f"{tier1.next_step_line or 'not recorded'} The decision brief is the "
            "service's answer to the same question from a completed run, and it "
            "is relayed here exactly as returned."
        )
    if check_id == "list-runs":
        return (
            "Four of the checks above need a completed run id and none was given "
            "(--run-id). This lists the completed runs your account already has."
        )
    if check_id == "bounded-run":
        if tier1.knob_count == 0:
            return (
                f"{len(tier1.entry_points)} entry point(s) declare 0 knobs, so "
                "every trial would evaluate the same configuration. Define a "
                "configuration space first with `traigent-optimize-config-space`; "
                "there is nothing for a run to search yet."
            )
        if tier1.read_knob_count == 0:
            return (
                f"{tier1.knob_count} knob(s) are declared and the decorated body "
                "reads none of them, so varying them cannot change the output. "
                "Rework the configuration space with "
                "`traigent-optimize-config-space` before spending anything."
            )
        missing = []
        if not tier1.datasets:
            missing.append(
                f"no evaluation dataset among {tier1.dataset_candidates} "
                "JSONL/JSON/CSV file(s) (`traigent-dataset-curate` builds one)"
            )
        if not tier1.scorers:
            missing.append(
                f"no scorer in {tier1.python_files} Python file(s) "
                "(`traigent-eval-build` wires one)"
            )
        if missing:
            return (
                f"{tier1.read_knob_count} of {tier1.knob_count} declared knob(s) "
                f"are read by the decorated body, but Tier 1 found "
                f"{' and '.join(missing)}, so a run would have nothing to score "
                "a configuration against."
            )
        return (
            f"{tier1.read_knob_count} of {tier1.knob_count} declared knob(s) are "
            "read by the decorated body, and a dataset and scorer exist. Whether "
            "tuning moves the score is the one question only a real run answers."
        )
    if check_id == "stop-here":
        return (
            "Tier 1 named a local next step and it is still open: "
            f"{tier1.next_step_line or 'not recorded'} Every reader above needs a "
            "completed run you do not have, and the service may abstain or return "
            "nothing even once you do — so a run bought to make it answer buys "
            "nothing you can count on."
        )
    return ""


def applicable(check_id: str, tier1: Tier1, run_id: str | None,
               want_list_runs: bool) -> tuple[bool, str]:
    """Whether a card is offered at all, and why not when it is not."""
    if check_id == "model-ids" and not tier1.model_ids:
        return False, (
            "no model id was declared in any configuration space, so there is "
            "nothing to validate"
        )
    if check_id == "list-runs" and not want_list_runs:
        return False, "pass --list-runs to be offered the run-discovery helper"
    return True, ""


def blocked_reason(check_id: str, tier1: Tier1, run_id: str | None,
                   cost_limit: float | None) -> str:
    """Why an offered card cannot be approved yet — empty when it can."""
    if check_id in RUN_DEPENDENT and not run_id:
        return (
            "needs a completed run; pass --run-id, or re-run this script with "
            "--list-runs and approve `list-runs` to find one, or hand over to "
            "`traigent-optimize-run` to produce one"
        )
    if check_id == "plan" and cost_limit is None:
        return "needs --cost-limit; the cap is yours to set, not the service's"
    if check_id == "bounded-run":
        return "never executed by this skill; `traigent-optimize-run` owns it"
    if check_id == "stop-here":
        return (
            "nothing to approve: this is the option of doing nothing further "
            "here, and it is a complete outcome"
        )
    return ""


def recommended_id(tier1: Tier1, run_id: str | None,
                   offered: list[str]) -> str | None:
    """One recommendation, chosen by Tier 1's own ladder.

    Two rules, in this order:

    1. With a completed run in hand, read it — a scorer nobody trusts is read
       about before a dataset is grown, because the dataset would otherwise be
       measured with that scorer.
    2. With NO run, and a Tier 1 next step that is local work (anything but the
       all-clear branch `g`), the recommendation is to STOP and do that local
       work. Recommending a reader here would mean recommending a paid run whose
       only purpose is to make an analysis service answer, and the service may
       still abstain. `plan` is recommended only when Tier 1 found nothing left
       to fix locally, which is exactly when sizing a first run is the question.
    """
    if run_id:
        if tier1.branch in {"d", "e"} and "evaluator-quality" in offered:
            return "evaluator-quality"
        if tier1.branch == "f" and "example-insights" in offered:
            return "example-insights"
        if "decision-brief" in offered:
            return "decision-brief"
    if tier1.branch and tier1.branch != "g" and "stop-here" in offered:
        return "stop-here"
    if "plan" in offered:
        return "plan"
    return offered[0] if offered else None


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


def resolve_backend_url(flag: str | None) -> str:
    return flag or os.getenv(BACKEND_URL_ENV_NAME) or DEFAULT_BACKEND_URL


def check_backend_url(url: str) -> str:
    """Accept an ORIGIN over https; accept plain http only on loopback.

    The backend URL is the origin — `https://portal.traigent.ai`, with no
    `/api/v1`. Appending the prefix here doubles it on every path this script
    builds, which is the shape that made `traigent plan` 404 on the dogfood run.
    It is refused rather than silently repaired, because the same URL is what the
    user pastes into the other skills.
    """
    parts = urlsplit(url)
    trimmed = url.rstrip("/")
    if parts.path.strip("/"):
        raise ValueError(
            f"refusing backend URL {url!r}: pass the ORIGIN with no path — "
            f"{DEFAULT_BACKEND_URL}, not {DEFAULT_BACKEND_URL}/api/v1. Every path "
            "this script sends already begins with /api/v1, and a base URL "
            "carrying it again produces a doubled path that 404s."
        )
    if parts.scheme == "https" and parts.hostname:
        return trimmed
    if parts.scheme == "http" and is_loopback(parts.hostname):
        return trimmed
    raise ValueError(
        f"refusing backend URL {url!r}: an API key travels in a request header, "
        "so the transport must be https (plain http is accepted only on the "
        "loopback interface, for a local test server)"
    )


def segment(value: object) -> str:
    """One URL path segment, safe to interpolate.

    Everything that becomes a path segment goes through here: the run id the user
    supplies AND the experiment id the SERVER hands back. A `..` in either walked
    the request to a different endpoint than the receipt recorded, because httpx
    normalizes the path after this script builds it — so the escaping happens
    before the string is a path, not after.

    Quoting alone is not enough for one case: `.` is unreserved, so `quote("..")`
    is `".."`, still a dot segment a normalizer will resolve. A segment that is
    nothing but dots therefore has its dots encoded too. Ordinary ids keep their
    dots and stay readable in the receipt.
    """
    quoted = quote(str(value), safe="")
    if quoted and set(quoted) == {"."}:
        return quoted.replace(".", "%2E")
    return quoted


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def sdk_user_agent() -> str | None:
    """``traigent-sdk/<installed version>`` — the SDK's own User-Agent.

    Read from the installed distribution's metadata, which does not import
    ``traigent``. The portal rejects the standard-library default User-Agent at
    the edge, so a request without this one never reaches the service.
    """
    import importlib.metadata as metadata

    try:
        return f"traigent-sdk/{metadata.version('traigent')}"
    except metadata.PackageNotFoundError:
        return None


@dataclass
class Transport:
    """Every HTTP request Tier 2 makes, and the receipt of having made it."""

    backend_url: str
    api_key: str
    user_agent: str
    timeout: float
    requests: list[dict] = field(default_factory=list)
    _client: object | None = None

    def headers(self) -> dict[str, str]:
        return {API_KEY_HEADER: self.api_key, "User-Agent": self.user_agent}

    def client(self):
        import httpx

        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def request(self, method: str, path: str) -> tuple[object | None, dict]:
        """Perform one request and return ``(parsed body or None, receipt row)``.

        The receipt records the path that was actually PUT ON THE WIRE, read back
        off the request object, not the string this script assembled. httpx
        resolves `..` segments and drops anything after `#` after the caller
        hands it a URL, so the two can differ — and a receipt that disagrees with
        the server's own log is worse than no receipt.
        """
        started = time.monotonic()
        entry: dict = {"method": method, "path": path, "path_sent": False}
        try:
            response = self.client().request(
                method, self.backend_url + path, headers=self.headers()
            )
        except Exception as exc:  # noqa: BLE001 - the TYPE is all that is relayed
            entry.update(
                {
                    "status": None,
                    "response_bytes": 0,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    "error_type": type(exc).__name__,
                }
            )
            self.requests.append(entry)
            return None, entry

        body = response.content
        entry.update(
            {
                "path": response.request.url.raw_path.decode("ascii", "replace"),
                "path_sent": True,
                "status": int(response.status_code),
                "response_bytes": len(body),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            }
        )
        self.requests.append(entry)
        if response.status_code != 200:
            return None, entry
        try:
            return json.loads(body.decode("utf-8")), entry
        except (UnicodeDecodeError, ValueError):
            entry["unparsable_body"] = True
            return None, entry


def envelope_data(payload: object) -> dict | None:
    """The service's ``data`` object, or None when the envelope is not one."""
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is not True:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def safe_dump(value: object, api_key: str) -> str | None:
    """Serialize a service payload, refusing if it echoes the key back."""
    text = json.dumps(value, indent=2, sort_keys=True)
    if api_key and api_key in text:
        return None
    return text


# --------------------------------------------------------------------------
# relaying a verdict, as returned
# --------------------------------------------------------------------------


def relay_lines(data: dict) -> list[str]:
    """Statements about the payload that are TRUE OF THE PAYLOAD, and nothing more.

    Nothing here infers, upgrades or scores. An abstain is said to be an
    abstain; an empty list is said to be empty; a confidence is quoted.
    """
    lines: list[str] = []
    status = data.get("status")
    if isinstance(status, str) and status.lower() == "abstain":
        lines.append(
            f"the service abstained (reason: {data.get('reason')!r}). "
            "This is not a pass — no verdict was produced."
        )
    elif isinstance(status, str):
        lines.append(f"`status: {status}`, relayed as returned.")

    anchor = data.get("anchor")
    if isinstance(anchor, dict) and "anchor_type" in anchor:
        lines.append(f"`anchor.anchor_type: {anchor['anchor_type']}`.")

    evaluators = data.get("evaluators")
    if isinstance(evaluators, list) and not evaluators:
        lines.append("no evaluator was assessed (`evaluators: []`).")

    rows = data.get("example_rows")
    if isinstance(rows, list) and not rows:
        lines.append("no example rows were returned (`example_rows: []`).")

    # The same field name appears at the top level AND inside `summary`, with
    # different values. Printing both unlabelled read as one field contradicting
    # itself, so the nested scope is named.
    for prefix, scope in (("", data), ("summary.", data.get("summary"))):
        if not isinstance(scope, dict):
            continue
        for key in ("dataset_quality", "example_count", "recommendation",
                    "computed", "privacy_mode"):
            if key in scope:
                lines.append(
                    f"`{prefix}{key}: {scope[key]!r}`, relayed as returned."
                )

    brief = data.get("decision_brief")
    if isinstance(brief, dict):
        for key in ("headline", "confidence"):
            if key in brief:
                lines.append(f"`{key}: {brief[key]!r}`, relayed as returned.")
        if "confidence" in brief:
            lines.append(
                "a confidence is never upgraded here: it is printed at the level "
                "the service returned."
            )
    elif "confidence" in data:
        lines.append(f"`confidence: {data['confidence']!r}`, relayed as returned.")

    if not lines:
        lines.append(
            "the payload carried none of the fields this check knows how to "
            "summarise; read the verbatim body above."
        )
    return lines


UNEXPECTED = (
    "the service returned an unexpected payload — no `success: true` envelope "
    "with a `data` object. No verdict is relayed and none is guessed. The "
    "receipt records the request."
)


def report_result(check_id: str, entry: dict, payload: object, api_key: str,
                  out: list[str]) -> dict:
    """Print one endpoint's outcome honestly and return the relay record."""
    status = entry.get("status")
    shown = f"{entry['method']} {entry['path']} -> "
    if status is None:
        shown += f"no response ({entry.get('error_type', 'unknown error')})"
    else:
        shown += (
            f"{status}, {entry['response_bytes']} byte(s), "
            f"{entry['elapsed_ms']} ms"
        )
    out.append(shown)

    record: dict = {"check": check_id, "request": entry}
    if status is None:
        out.append(
            "  the request did not complete. Only the exception TYPE is shown: a "
            "message can carry a key."
        )
        record["relayed"] = False
        return record
    if status != 200:
        out.append(
            f"  HTTP {status}. The body is NOT relayed (only its length above): an "
            "error body has been observed echoing the request back, key included. "
            "Read the status, not a guess."
        )
        record["relayed"] = False
        return record

    data = envelope_data(payload)
    if data is None:
        out.append(f"  {UNEXPECTED}")
        record["relayed"] = False
        record["unexpected_payload"] = True
        return record

    dumped = safe_dump(data, api_key)
    if dumped is None:
        out.append(
            "  the response echoed a value equal to your API key. It is NOT "
            "shown. Rotate the key and report this."
        )
        record["relayed"] = False
        record["key_echo_refused"] = True
        return record

    out.append("  the service returned, verbatim:")
    out.extend("  " + line for line in dumped.splitlines())
    out.append("  relayed as returned:")
    for line in relay_lines(data):
        out.append(f"  - {line}")
    record["relayed"] = True
    record["data"] = data
    return record


# --------------------------------------------------------------------------
# the checks themselves
# --------------------------------------------------------------------------


def run_evaluator_quality(transport: Transport, run_id: str, out: list[str]) -> dict:
    payload, entry = transport.request(
        "GET", f"/api/v1/analytics/runs/{segment(run_id)}/evaluator-quality"
    )
    return report_result("evaluator-quality", entry, payload, transport.api_key, out)


def run_example_insights(transport: Transport, run_id: str, out: list[str]) -> dict:
    payload, entry = transport.request(
        "GET", f"/api/v1/analytics/runs/{segment(run_id)}/example-insights"
    )
    return report_result("example-insights", entry, payload, transport.api_key, out)


def run_decision_brief(transport: Transport, run_id: str, out: list[str]) -> dict:
    payload, entry = transport.request(
        "GET", f"/api/v1/analytics/runs/{segment(run_id)}/decision-payload"
    )
    return report_result("decision-brief", entry, payload, transport.api_key, out)


def run_example_scoring(transport: Transport, run_id: str, out: list[str]) -> dict:
    """A READER. It never starts a scoring job.

    The compute endpoint that would produce a result returned HTTP 500 on the
    dogfood run of 2026-09-13, and a successful GET proves nothing about it. Until
    there is a successful runtime witness AND a known charging boundary, this
    check reads what already exists and stops. ``computed: false`` means NOT
    COMPUTED — it is never read here as permission to POST.
    """
    base = f"/api/v1/analytics/example-scoring/{segment(run_id)}"
    payload, entry = transport.request("GET", f"{base}/summary")
    record = report_result("example-scoring", entry, payload, transport.api_key, out)
    data = envelope_data(payload)
    if data is None:
        return record

    if data.get("computed") is not True:
        out.append(
            "  the scoring service has not computed results for this run "
            "(`computed: false`). That is the end of this check: this skill does "
            "not trigger scoring, so nothing here can start a job, and no "
            "conclusion about your rows follows from it."
        )
        record["computed"] = False
        return record

    payload, entry = transport.request("GET", f"{base}/dataset-quality")
    report_result("example-scoring", entry, payload, transport.api_key, out)
    record["computed"] = True
    return record


def run_list_runs(transport: Transport, out: list[str]) -> dict:
    """List completed PORTAL runs with enough context to choose one by hand.

    Nothing is auto-selected. Silently taking the newest run means silently
    analysing someone else's experiment, and the run id is the one input every
    reader depends on.
    """
    payload, entry = transport.request(
        "GET", f"/api/v1/experiments?limit={EXPERIMENTS_PAGE_LIMIT}"
    )
    record = report_result("list-runs", entry, payload, transport.api_key, out)
    experiments = as_list(envelope_data(payload), ("experiments", "items", "results"))
    if not experiments:
        out.append(
            "  no experiment was listed, so no run id can be offered from here."
        )
        return record

    # One approval buys a BOUNDED number of requests. A server answering a
    # limit=10 page with 500 experiments must not turn one approval into 501
    # authenticated requests, so the page size is enforced here as well as asked
    # for in the query.
    over_page = max(0, len(experiments) - EXPERIMENTS_PAGE_LIMIT)
    if over_page:
        out.append(
            f"  the reply carried {len(experiments)} experiment(s) for a "
            f"limit={EXPERIMENTS_PAGE_LIMIT} page. Only the first "
            f"{EXPERIMENTS_PAGE_LIMIT} are read: one approval is one bounded set "
            f"of requests, so {over_page} were not fetched."
        )
        experiments = experiments[:EXPERIMENTS_PAGE_LIMIT]

    rows: list[dict] = []
    for experiment in experiments:
        experiment_id = experiment.get("experiment_id") or experiment.get("id")
        if not experiment_id:
            continue
        payload, entry = transport.request(
            "GET", f"/api/v1/experiment-runs/{segment(experiment_id)}/runs"
        )
        report_result("list-runs", entry, payload, transport.api_key, out)
        for run in as_list(envelope_data(payload), ("runs", "items", "results")):
            if run.get("run_id"):
                rows.append({"experiment": experiment, "run": run})

    completed = [row for row in rows
                 if str(row["run"].get("status") or "").lower()
                 in {"completed", "complete"}]
    completed.sort(key=lambda row: str(row["run"].get("completed_at") or ""),
                   reverse=True)

    out.append("  completed portal runs, newest first:")
    if not completed:
        out.append("  - none. No completed run exists on this account yet.")
    for row in completed:
        experiment, run = row["experiment"], row["run"]
        out.append(f"  - portal run id : {run.get('run_id')}")
        out.append(f"    project id    : {_first(experiment, run, 'project_id')}")
        out.append(f"    experiment id : {_first(experiment, run, 'experiment_id', 'id')}")
        out.append(f"    experiment    : {_first(experiment, run, 'name', 'description')}")
        out.append(f"    status        : {run.get('status')}")
        out.append(f"    completed_at  : {run.get('completed_at')}")
        out.append(
            f"    configuration runs: "
            f"{_first(run, experiment, 'configuration_runs_count', 'configuration_runs', 'trial_count')}"
        )
        out.append(f"    description   : {run.get('description')}")
    out.append(
        f"  this listing asked for at most {EXPERIMENTS_PAGE_LIMIT} experiment(s) "
        f"and got {len(experiments)}"
        + (
            "; the page is full, so more experiments may exist than are shown here."
            if len(experiments) >= EXPERIMENTS_PAGE_LIMIT
            else "."
        )
    )
    out.append(
        "  nothing is selected for you: pass the one you want as --run-id. A "
        "LOCAL session id (a `tv0_` id, or an `optimization_id` out of a local "
        "session file) is not a portal run id and returns 404 on every analytics "
        "endpoint."
    )
    record["completed_runs"] = [row["run"].get("run_id") for row in completed]
    record["experiments_listed"] = len(experiments)
    return record


def _first(primary: dict, secondary: dict, *keys: str) -> object:
    """The first of ``keys`` present in either payload, or a plain 'not returned'.

    The live probe recorded which KEYS these endpoints carry, not a schema, so a
    missing field is reported as missing instead of being invented or dropped.
    """
    for source in (primary, secondary):
        for key in keys:
            if isinstance(source, dict) and source.get(key) is not None:
                return source[key]
    return "not returned by this endpoint"


def as_list(data: dict | None, keys: tuple[str, ...]) -> list[dict]:
    """Pull a list of objects out of a payload whose exact shape is not pinned.

    The live probe recorded the KEYS these endpoints return, not the envelope
    around them, so both ``data`` as a list and ``data[<key>]`` as a list are
    accepted rather than guessed at.
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


# --------------------------------------------------------------------------
# the two CLI-backed checks
# --------------------------------------------------------------------------


def provider_for(model_id: str) -> str | None:
    lowered = model_id.lower()
    for prefix, provider in PROVIDER_PREFIXES:
        if lowered.startswith(prefix):
            return provider
    return None


def run_cli(argv: list[str], subprocesses: list[dict], out: list[str]) -> dict | None:
    """Run one `traigent` command, record its argv, and return parsed JSON.

    The key is never on the command line: the SDK reads it from the environment
    this process already has, so the recorded argv is safe to print and to keep.
    """
    executable = shutil.which(argv[0])
    if executable is None:
        out.append(
            f"  `{argv[0]}` is not on PATH, so this check cannot run. Install the "
            "SDK (`pip install \"traigent>=0.27.0\"`) and try again."
        )
        return None
    record: dict = {"argv": list(argv)}
    try:
        completed = subprocess.run(
            [executable, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        record["error_type"] = type(exc).__name__
        subprocesses.append(record)
        out.append(f"  the command did not complete ({type(exc).__name__}).")
        return None
    record["returncode"] = completed.returncode
    record["stdout_bytes"] = len(completed.stdout.encode("utf-8"))
    record["stderr_bytes"] = len(completed.stderr.encode("utf-8"))
    subprocesses.append(record)
    out.append(f"  $ {' '.join(argv)}")
    out.append(f"  exit {completed.returncode}, "
               f"{record['stdout_bytes']} byte(s) of stdout")
    if completed.returncode != 0:
        out.append(
            "  the command failed. Its output is not relayed here — stderr has "
            "been observed carrying a key. Re-run the command yourself to read it."
        )
        return None
    try:
        return json.loads(completed.stdout)
    except ValueError:
        out.append(
            "  the command printed something other than JSON, so nothing is "
            "relayed. Re-run it yourself to read the output."
        )
        return None


def run_model_ids(tier1: Tier1, subprocesses: list[dict], api_key: str,
                  out: list[str]) -> dict:
    record: dict = {"check": "model-ids", "results": []}
    for model_id in tier1.model_ids:
        provider = provider_for(model_id)
        if provider is None:
            out.append(
                f"  {model_id}: skipped — no provider can be inferred from the id, "
                "and guessing one would produce a confident wrong answer. Name it "
                "yourself with `traigent models --provider <provider> --check "
                f"{model_id} --json`."
            )
            record["results"].append({"model_id": model_id, "skipped": True})
            continue
        payload = run_cli(
            ["traigent", "models", "--provider", provider, "--check", model_id,
             "--json"],
            subprocesses,
            out,
        )
        if payload is None:
            record["results"].append({"model_id": model_id, "relayed": False})
            continue
        dumped = safe_dump(payload, api_key)
        if dumped is None:
            out.append("  the output echoed a value equal to your API key; not shown.")
            record["results"].append({"model_id": model_id, "relayed": False})
            continue
        out.append("  the CLI returned, verbatim:")
        out.extend("  " + line for line in dumped.splitlines())
        record["results"].append({"model_id": model_id, "relayed": True,
                                  "payload": payload})
    return record


def run_plan(tier1: Tier1, args, backend_url: str, subprocesses: list[dict],
             api_key: str, out: list[str]) -> dict:
    task = args.task or default_task(tier1)
    argv = [
        "traigent", "plan",
        "--backend-url", backend_url,
        "--task-description", task,
        "--dataset-size", str(tier1.dataset_size),
        "--has-holdout" if tier1.has_holdout else "--no-holdout",
        "--objective", args.objective,
        "--max-trials", str(args.max_trials),
        "--cost-limit", str(args.cost_limit),
        "--json",
    ]
    out.append(
        f"  the numbers sent are yours: dataset-size {tier1.dataset_size} (Tier 1 "
        f"row count), holdout {'yes' if tier1.has_holdout else 'no'}, max-trials "
        f"{args.max_trials}, cost-limit {args.cost_limit} USD (your cap)."
    )
    payload = run_cli(argv, subprocesses, out)
    record: dict = {"check": "plan", "relayed": False}
    if payload is None:
        return record
    dumped = safe_dump(payload, api_key)
    if dumped is None:
        out.append("  the output echoed a value equal to your API key; not shown.")
        return record
    out.append("  the service returned, verbatim:")
    out.extend("  " + line for line in dumped.splitlines())
    out.append(
        f"  the plan's cost limit is the {args.cost_limit} USD cap YOU passed, "
        "echoed back. It is not a budget the service authored, and nothing here "
        "computes one."
    )
    evidence = find_key(payload, "evidence_level")
    out.append(
        f"  `evidence_level: {evidence!r}`, relayed verbatim."
        if evidence is not None
        else "  the payload carried no `evidence_level`."
    )
    objectives = find_key(payload, "objectives")
    if objectives is None:
        out.append("  the payload carried no `objectives` block to show.")
    else:
        out.append("  `objectives`, as returned — read the orientation yourself:")
        out.extend("  " + line
                   for line in json.dumps(objectives, indent=2,
                                          sort_keys=True).splitlines())
    out.append(
        "  the plan's steps are ADVISORY text, not a script. They have been "
        "observed naming a command that is not in the installed CLI and "
        "returning a cost objective oriented to maximize; check any command "
        "against `--help` before running it, and read the orientation above "
        "rather than assuming it."
    )
    record.update({"relayed": True, "payload": payload})
    return record


def find_key(payload: object, key: str) -> object | None:
    """The first value for ``key`` anywhere in a payload of unpinned shape.

    The plan CLI prints the raw backend payload and the probe recorded its
    FIELDS, not its envelope. Searching for the field is honest about that;
    hard-coding a path would quietly print nothing the day the envelope moves.
    """
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_key(item, key)
            if found is not None:
                return found
    return None


def default_task(tier1: Tier1) -> str:
    if tier1.entry_points:
        entry = tier1.entry_points[0]
        return (
            f"optimize the {entry.get('function')} function in "
            f"{entry.get('file')}"
        )
    return "optimize an LLM agent function audited by traigent-setup-audit"


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render_card(check: Check, tier1: Tier1, run_id: str | None, backend_url: str,
                blocked: str, is_recommended: str, invocation: str) -> list[str]:
    lines = ["=" * 72]
    suffix = "   (recommended)" if is_recommended else ""
    lines.append(f"APPROVAL CARD — {check.id}{suffix}")
    lines.append("=" * 72)
    lines.append(f"Question it answers : {check.question}")
    lines.append(f"What it retrieves   : {check.offer}")
    lines.append(f"Caveat              : {check.caveat}.")
    lines.append(f"Why, in your numbers: {motivation(check.id, tier1, run_id)}")
    lines.append(f"What runs           : {check.runs}")
    if check.endpoints:
        lines.append(f"                      against {backend_url}")
    lines.append(f"Leaves this machine : {check.egress}.")
    lines.append(f"Your API key        : {check.key_line}.")
    lines.append(f"Cost                : {check.cost}")
    lines.append(f"Needs               : {check.needs}")
    lines.append(f"Stop rule           : {check.stop_rule}")
    if check.id == "stop-here":
        lines.append(
            "How to take it      : do nothing here. Act on the Tier 1 next step "
            "quoted above; this card needs no approval, and `--approve "
            "stop-here` is an error."
        )
    elif blocked:
        lines.append(f"BLOCKED             : {blocked}.")
    else:
        lines.append(f"Approve with        : {invocation}")
    return lines


def render_offer(tier1: Tier1, args, backend_url: str, guard: str,
                 cards: list[tuple[Check, str, bool]], skipped: list[tuple[str, str]],
                 invocations: dict[str, str]) -> str:
    out = [
        "# Traigent setup audit — Tier 2 offer",
        "",
        f"Offer mode. No network call was made: the network guard is installed "
        f"and reports `{guard}`, which is a measurement of this process, not a "
        f"claim about it.",
        "No process was spawned either — that half is by construction, not by "
        "the guard, which covers sockets only: the two checks that shell out are "
        "reachable only through `--approve`, and nothing here passed one.",
        f"Read from `{tier1.path}` ({TIER1_SCHEMA}, project `{tier1.root}`).",
        f"Backend that an approved check would call: {backend_url}",
        f"`{KEY_ENV_NAME}` is "
        + ("set in this environment (name only — the value is never read here)."
           if KEY_ENV_NAME in os.environ else
           "NOT set. A backend check cannot run without it."),
        "",
        "Each card below is an offer, not a plan. Approve the ones you want, one "
        "`--approve <check-id>` each.",
        "",
    ]
    for check, blocked, is_recommended in cards:
        out.extend(
            render_card(check, tier1, args.run_id, backend_url, blocked,
                        "recommended" if is_recommended else "",
                        invocations[check.id])
        )
        out.append("")
    if skipped:
        out.append("## Not offered")
        out.append("")
        for check_id, reason in skipped:
            out.append(f"- `{check_id}`: {reason}.")
        out.append("")
    out.append("## What you get back, and what you do not")
    out.append("")
    out.extend(
        [
            "- Verdicts are relayed exactly as the service returns them. An "
            "abstain is printed as an abstain and is not a pass; a `low` "
            "confidence stays `low`.",
            "- No budget is computed here. Every number printed is the service's "
            "own or the cap you passed.",
            "- No lift is promised by any of this. A flat or negative result is a "
            "real outcome.",
            "- Every approved run writes a receipt (`--receipt <path>`) listing "
            "each request and each process. Keep it: it is the record of what "
            "left this machine.",
            f"- {STOP_SENTENCE}",
        ]
    )
    out.append("")
    # Cards quote the audited project's own text — model ids, dataset file
    # names, a source line. A planted escape sequence in any of them rewrites
    # the line the user is reading, consent lines included, so the whole card
    # goes through the Tier 1 filter rather than each interpolation separately.
    return "\n".join(printable_text(line) for line in out)


def invocation_for(check_id: str, args, script: str) -> str:
    parts = [f"python3 {script}", f"--from-audit {args.from_audit}"]
    if check_id in RUN_DEPENDENT and args.run_id:
        parts.append(f"--run-id {args.run_id}")
    if check_id == "plan":
        parts.append(f"--cost-limit {args.cost_limit if args.cost_limit is not None else '<usd>'}")
    if check_id == "list-runs":
        parts.append("--list-runs")
    parts.append(f"--approve {check_id}")
    parts.append("--receipt receipt.json")
    return " ".join(parts)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tier2_checks.py",
        # No abbreviations: `--appr <id>` must not be an approval this script
        # only discovers after it has decided it is in offer mode.
        allow_abbrev=False,
        description=(
            "Offer, and on explicit approval run, the Traigent-backed checks that "
            "answer what the free Tier 1 audit could not."
        ),
    )
    parser.add_argument("--from-audit", required=True,
                        help="the Tier 1 JSON report (audit_project.py --json)")
    parser.add_argument("--approve", action="append", default=[], metavar="CHECK_ID",
                        help="run this check; repeatable. Without it nothing runs.")
    parser.add_argument("--run-id", help="a completed run id the checks read")
    parser.add_argument("--list-runs", action="store_true",
                        help="also offer the run-discovery helper")
    parser.add_argument("--task", help="task description sent to the planning service")
    parser.add_argument("--objective", default=DEFAULT_OBJECTIVE,
                        help=f"objective name for the plan (default {DEFAULT_OBJECTIVE})")
    parser.add_argument("--max-trials", type=int, default=DEFAULT_MAX_TRIALS,
                        help=f"trial ceiling for the plan (default {DEFAULT_MAX_TRIALS})")
    parser.add_argument("--cost-limit", type=float,
                        help="YOUR spend cap in USD, required by the plan check")
    parser.add_argument("--backend-url",
                        help=f"backend base URL (else ${BACKEND_URL_ENV_NAME}, "
                             f"else {DEFAULT_BACKEND_URL})")
    parser.add_argument("--receipt", help="write the request/process receipt here")
    parser.add_argument("--json", dest="json_out",
                        help="also write this run's record as JSON")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="per-request timeout in seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # Parse FIRST, then decide the mode from the parsed namespace. Reading the
    # mode out of the raw argv text was wrong twice over: argparse used to accept
    # any unambiguous prefix, so `--appr <id>` was an approval the textual scan
    # did not see — it installed the guard and then ran run mode, which refused
    # its own request and wrote a receipt implying one had been attempted.
    # `allow_abbrev=False` closes the prefix, and the namespace is the authority
    # on what was asked for. Parsing opens no socket and spawns no process.
    try:
        args = parse_args(raw)
    except SystemExit:
        return 2

    guard = "not installed (run mode)"
    if not args.approve:
        install_network_guard()
        guard = verify_network_guard()

    try:
        tier1 = load_tier1(Path(args.from_audit).expanduser())
        backend_url = check_backend_url(resolve_backend_url(args.backend_url))
    except ValueError as exc:
        print(f"tier2_checks.py: {exc}", file=sys.stderr)
        return 2

    if args.run_id is not None and not RUN_ID_RE.match(args.run_id):
        print(
            "tier2_checks.py: --run-id is not a run id "
            "(expected 8-64 characters of letters, digits, `-` or `_`, which a "
            "portal run id always is). Nothing was requested. Find the id with "
            "--list-runs.",
            file=sys.stderr,
        )
        return 2

    unknown = [name for name in args.approve if name not in CATALOGUE_BY_ID]
    if unknown:
        print(
            "tier2_checks.py: no such check: " + ", ".join(sorted(unknown))
            + ". The catalogue is: " + ", ".join(check.id for check in CATALOGUE),
            file=sys.stderr,
        )
        return 2

    script = sys.argv[0] if argv is None else str(SCRIPT_DIR / "tier2_checks.py")
    invocations = {check.id: invocation_for(check.id, args, script)
                   for check in CATALOGUE}

    if not args.approve:
        cards: list[tuple[Check, str, bool]] = []
        skipped: list[tuple[str, str]] = []
        for check in CATALOGUE:
            offered, reason = applicable(check.id, tier1, args.run_id, args.list_runs)
            if not offered:
                skipped.append((check.id, reason))
                continue
            cards.append((check, blocked_reason(check.id, tier1, args.run_id,
                                                args.cost_limit), False))
        # The recommendation is chosen over every OFFERED card, not only the
        # unblocked ones: a card blocked for want of a run id or a cap is still
        # the right next thing to do, and its BLOCKED line says what to supply.
        # Choosing only among unblocked cards left a first-time user — no run,
        # no cap — with no recommendation at all, which is the one outcome the
        # ladder exists to prevent.
        chosen = recommended_id(tier1, args.run_id,
                                [check.id for check, _, _ in cards])
        cards = [(check, blocked, check.id == chosen) for check, blocked, _ in cards]
        print(render_offer(tier1, args, backend_url, guard, cards, skipped,
                           invocations))
        return 0

    return execute(args, tier1, backend_url, invocations)


def execute(args, tier1: Tier1, backend_url: str, invocations: dict[str, str]) -> int:
    """Run mode: only the approved checks, only their named endpoints."""
    approved = [check_id for check in CATALOGUE for check_id in [check.id]
                if check_id in args.approve]

    for check_id in approved:
        blocked = blocked_reason(check_id, tier1, args.run_id, args.cost_limit)
        if blocked:
            print(f"tier2_checks.py: `{check_id}` {blocked}", file=sys.stderr)
            return 2

    needs_backend = [check_id for check_id in approved if check_id != "model-ids"]
    api_key = os.getenv(KEY_ENV_NAME) or ""
    if needs_backend and not api_key:
        print(
            f"tier2_checks.py: {KEY_ENV_NAME} is not set in this environment, so "
            "no Traigent check can run. Set it and try again; its value is never "
            "printed or stored by this script.",
            file=sys.stderr,
        )
        return 2

    user_agent = sdk_user_agent()
    if needs_backend and user_agent is None:
        print(
            "tier2_checks.py: the traigent distribution is not installed, so the "
            "SDK's own User-Agent cannot be built. Install it "
            '(`pip install "traigent>=0.27.0"`) and try again.',
            file=sys.stderr,
        )
        return 2

    transport = Transport(
        backend_url=backend_url,
        api_key=api_key,
        user_agent=user_agent or "",
        timeout=args.timeout,
    )
    subprocesses: list[dict] = []
    records: list[dict] = []
    out: list[str] = [
        "# Traigent setup audit — Tier 2 run",
        "",
        f"Approved: {', '.join(approved)}. Nothing else ran.",
        f"Backend: {backend_url}",
        f"Read from `{tier1.path}`.",
        "",
    ]

    try:
        for check_id in approved:
            out.append(f"## {check_id}")
            out.append("")
            if check_id == "evaluator-quality":
                records.append(run_evaluator_quality(transport, args.run_id, out))
            elif check_id == "example-insights":
                records.append(run_example_insights(transport, args.run_id, out))
            elif check_id == "decision-brief":
                records.append(run_decision_brief(transport, args.run_id, out))
            elif check_id == "example-scoring":
                records.append(run_example_scoring(transport, args.run_id, out))
            elif check_id == "list-runs":
                records.append(run_list_runs(transport, out))
            elif check_id == "model-ids":
                records.append(run_model_ids(tier1, subprocesses, api_key, out))
            elif check_id == "plan":
                records.append(
                    run_plan(tier1, args, backend_url, subprocesses, api_key, out)
                )
            out.append("")
    finally:
        transport.close()

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "backend_url": backend_url,
        "approved": approved,
        "run_id": args.run_id,
        "from_audit": str(tier1.path),
        "requests": transport.requests,
        "subprocesses": subprocesses,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    if args.receipt:
        path = Path(args.receipt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        out.append(
            f"Receipt written to `{args.receipt}`: "
            f"{len(transport.requests)} request(s) and {len(subprocesses)} "
            f"process(es) were made — both counted, not assumed. "
            "Keep it: it is the record of what left this machine. No key is in it."
        )
    else:
        out.append(
            f"{len(transport.requests)} request(s) and {len(subprocesses)} "
            "process(es) were made. Pass --receipt <path> to keep the record."
        )
    out.append("")
    out.append(STOP_SENTENCE)

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema": SCHEMA, "receipt": receipt, "records": records},
                       indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )

    # Same filter as the offer: these lines carry the project's text AND the
    # service's, and neither is ours.
    print("\n".join(printable_text(line) for line in out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
