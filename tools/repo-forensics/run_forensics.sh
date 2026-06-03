#!/bin/bash

# Repo Forensics Suite Runner v2
# Created by Alex Greenshpun
# Usage: ./run_forensics.sh <repo_path> [--skill-scan|--ci|--ci-own] [--format text|json|summary]
#
# Modes:
#   (default)      Full audit — all 17 scanners (manual deep scan)
#   --skill-scan   9 scanners for vetting untrusted AI skills
#   --ci           13 scanners for CI on untrusted repos (skips scanners that
#                  overlap with Bandit/Semgrep/CodeQL/Gitleaks/pip-audit/OSV/ZAP)
#   --ci-own       6 low-noise scanners for CI on your OWN codebase (skips
#                  threat-hunting scanners that assume untrusted code)
#
# Exit codes:
#   0 = clean (all scanners ran, no findings)
#   1 = high/medium findings
#   2 = critical findings
#   3 = infrastructure failure (no scanners completed)
#
# CI/CD integration (GitHub Actions):
#   Use a SHA-pinned tarball download — never git clone. This avoids:
#   - Unpinned code execution (supply chain risk)
#   - Token leakage in .git/config
#
#   Example workflow step:
#     env:
#       FORENSICS_SHA: <full-40-char-sha>
#     steps:
#     - name: Fetch repo-forensics (pinned)
#       run: |
#         mkdir -p /tmp/agents-skills
#         curl -fsSL \
#           -H "Authorization: token ${{ secrets.YOUR_PAT }}" \
#           "https://api.github.com/repos/OWNER/agents-skills/tarball/${FORENSICS_SHA}" \
#           | tar xz -C /tmp/agents-skills --strip-components=1
#     - name: Run forensics
#       continue-on-error: true  # remove once scanner is tuned for your repo
#       run: |
#         bash /tmp/agents-skills/skills/repo-forensics/skill/scripts/run_forensics.sh \
#           "$GITHUB_WORKSPACE" --ci-own --format summary
#
#   Check "SCANNERS: X/Y completed" in output to verify scanners actually ran.
#   Exit code 3 means zero scanners completed (config/infra problem).

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: $0 <repo_path> [--skill-scan] [--format text|json|summary] [--update-iocs] [--watch]"
    echo ""
    echo "Modes:"
    echo "  (default)      Full audit - all 17 scanners"
    echo "  --skill-scan   Focused on AI skill threats (9 scanners, faster)"
    echo "  --ci           CI/CD mode for untrusted repos - 13 non-overlapping scanners"
    echo "  --ci-own       CI/CD mode for your own repo - 6 low-noise scanners"
    echo "                 (infra, lifecycle, manifest_drift, binary, git_forensics, integrity)"
    echo ""
    echo "Options:"
    echo "  --format text     Human-readable with severity colors (default)"
    echo "  --format json     Machine-readable JSON"
    echo "  --format summary  Counts only (for CI/CD)"
    echo "  --update-iocs     Pull latest IOC database before scanning"
    echo "  --watch           Enable file integrity baseline tracking"
    exit 1
fi

REPO_PATH=$(realpath "$1")
shift

# Parse remaining args
SKILL_SCAN=false
CI_MODE=false
CI_OWN_MODE=false
FORMAT="text"
UPDATE_IOCS=false
WATCH_MODE=false
VERIFY_INSTALL=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skill-scan) SKILL_SCAN=true; shift ;;
        --ci) CI_MODE=true; shift ;;
        --ci-own) CI_OWN_MODE=true; shift ;;
        --format) [[ $# -ge 2 ]] || { echo "Error: --format requires a value"; exit 1; }; FORMAT="$2"; shift 2 ;;
        --update-iocs) UPDATE_IOCS=true; shift ;;
        --watch) WATCH_MODE=true; shift ;;
        --verify-install) VERIFY_INSTALL=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Handle --verify-install (standalone, exits after)
if $VERIFY_INSTALL; then
    python3 "$SKILL_DIR/verify_install.py" --verify
    exit $?
fi

# Handle --update-iocs before scanning
if $UPDATE_IOCS; then
    echo "[*] Updating IOC database..."
    python3 "$SKILL_DIR/ioc_manager.py" --update
fi
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "=========================================="
echo "  REPO FORENSICS v2"
echo "  Target: $REPO_PATH"
echo "  Mode: $(if $CI_OWN_MODE; then echo 'CI/CD Own Repo (low-noise)'; elif $CI_MODE; then echo 'CI/CD (no-overlap)'; elif $SKILL_SCAN; then echo 'Skill Scan (focused)'; else echo 'Full Audit'; fi)"
echo "  Format: $FORMAT"
echo "  Date: $(date)"
echo "=========================================="

SCANNER_TIMEOUT=120

# Portable timeout (macOS lacks GNU timeout)
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD="gtimeout"
fi

EXPECTED_SCANNERS=0

run_scanner() {
    local name="$1"
    local script="$2"
    local extra_args="${3:-}"
    local output_file="$TMPDIR/$name.out"
    local exit_file="$TMPDIR/$name.exit"
    local err_file="$TMPDIR/$name.err"
    EXPECTED_SCANNERS=$((EXPECTED_SCANNERS + 1))

    # Guard against missing scanner scripts. Without this check, python3
    # exits 2 ("can't open file") which the result loop would mis-interpret
    # as "scanner ran with critical findings" — causing silent infra failure.
    # Emit exit 127 (conventional for command-not-found) so the loop counts
    # it as a failed scanner, triggering exit-3 downstream when all are missing.
    if [ ! -f "$SKILL_DIR/$script" ]; then
        echo "Scanner script not found: $SKILL_DIR/$script" > "$err_file"
        : > "$output_file"
        echo "127" > "$exit_file"
        return
    fi

    if [ -n "$TIMEOUT_CMD" ]; then
        $TIMEOUT_CMD "$SCANNER_TIMEOUT" python3 "$SKILL_DIR/$script" "$REPO_PATH" --format "$FORMAT" ${extra_args:+"$extra_args"} > "$output_file" 2>"$err_file"
    else
        python3 "$SKILL_DIR/$script" "$REPO_PATH" --format "$FORMAT" ${extra_args:+"$extra_args"} > "$output_file" 2>"$err_file"
    fi
    echo $? > "$exit_file"
}

if $CI_OWN_MODE; then
    # CI/CD mode for scanning your own repo. Only scanners that produce
    # actionable findings on trusted codebases (not threat-hunting scanners
    # designed for vetting untrusted third-party code).
    echo ""
    echo "[*] Running CI/CD own-repo scan (6 low-noise scanners)..."

    run_scanner "infra" "scan_infra.py" &
    run_scanner "lifecycle" "scan_lifecycle.py" &
    run_scanner "manifest_drift" "scan_manifest_drift.py" &
    run_scanner "binary" "scan_binary.py" &
    run_scanner "git_forensics" "scan_git_forensics.py" &
    run_scanner "integrity" "scan_integrity.py" &
    wait

elif $CI_MODE; then
    # CI/CD mode: 13 scanners that do NOT overlap with Bandit, Semgrep, CodeQL,
    # Gitleaks, pip-audit, OSV Scanner, or OWASP ZAP.
    # Skipped (already covered): scan_secrets, scan_sast, scan_dependencies, scan_dast
    echo ""
    echo "[*] Running CI/CD scan (13 non-overlapping scanners)..."

    run_scanner "skill_threats" "scan_skill_threats.py" &
    run_scanner "mcp_security" "scan_mcp_security.py" &
    run_scanner "openclaw_skills" "scan_openclaw_skills.py" &
    run_scanner "lifecycle" "scan_lifecycle.py" &
    run_scanner "manifest_drift" "scan_manifest_drift.py" &
    run_scanner "runtime_dynamism" "scan_runtime_dynamism.py" &
    run_scanner "binary" "scan_binary.py" &
    run_scanner "git_forensics" "scan_git_forensics.py" &
    run_scanner "ast_analysis" "scan_ast.py" &
    run_scanner "entropy" "scan_entropy.py" &
    run_scanner "dataflow" "scan_dataflow.py" &
    run_scanner "infra" "scan_infra.py" &
    run_scanner "integrity" "scan_integrity.py" &
    wait

elif $SKILL_SCAN; then
    # Focused mode: 9 scanners most relevant to vetting skills
    echo ""
    echo "[*] Running focused skill scan (9 scanners)..."

    run_scanner "skill_threats" "scan_skill_threats.py" &
    run_scanner "secrets" "scan_secrets.py" &
    run_scanner "dataflow" "scan_dataflow.py" &
    run_scanner "sast" "scan_sast.py" &
    run_scanner "lifecycle" "scan_lifecycle.py" &
    run_scanner "mcp_security" "scan_mcp_security.py" &
    run_scanner "runtime_dynamism" "scan_runtime_dynamism.py" &
    run_scanner "manifest_drift" "scan_manifest_drift.py" &
    run_scanner "openclaw_skills" "scan_openclaw_skills.py" &
    wait

else
    # Full audit: all scanners in parallel
    echo ""
    echo "[*] Running all 17 scanners in parallel..."
    run_scanner "entropy" "scan_entropy.py" &
    run_scanner "binary" "scan_binary.py" &
    run_scanner "git_forensics" "scan_git_forensics.py" &
    run_scanner "dependencies" "scan_dependencies.py" &
    run_scanner "secrets" "scan_secrets.py" &
    run_scanner "sast" "scan_sast.py" &
    run_scanner "infra" "scan_infra.py" &
    run_scanner "lifecycle" "scan_lifecycle.py" &
    run_scanner "skill_threats" "scan_skill_threats.py" &
    run_scanner "dataflow" "scan_dataflow.py" &
    run_scanner "mcp_security" "scan_mcp_security.py" &
    run_scanner "ast_analysis" "scan_ast.py" &
    run_scanner "runtime_dynamism" "scan_runtime_dynamism.py" &
    run_scanner "manifest_drift" "scan_manifest_drift.py" &
    run_scanner "openclaw_skills" "scan_openclaw_skills.py" &
    if $WATCH_MODE; then
        run_scanner "integrity" "scan_integrity.py" "--watch" &
    else
        run_scanner "integrity" "scan_integrity.py" &
    fi
    run_scanner "dast" "scan_dast.py" &
    wait
fi

# Collect and display results
echo ""
echo "=========================================="
echo "  RESULTS"
echo "=========================================="

MAX_EXIT=0
TOTAL_C=0
TOTAL_H=0
TOTAL_M=0
TOTAL_L=0
COMPLETED_SCANNERS=0
FAILED_SCANNERS=0

for out_file in "$TMPDIR"/*.out; do
    name=$(basename "$out_file" .out)
    exit_code=$(cat "$TMPDIR/$name.exit" 2>/dev/null || echo "1")

    echo ""
    echo "--- [$name] ---"
    cat "$out_file"

    # Show scanner errors if any
    if [ -s "$TMPDIR/$name.err" ]; then
        echo "  [stderr]:"
        cat "$TMPDIR/$name.err"
    fi

    # Track scanner completion (exit 0/1/2 = ran successfully, other = infra failure)
    if [ "$exit_code" -le 2 ]; then
        COMPLETED_SCANNERS=$((COMPLETED_SCANNERS + 1))
    else
        FAILED_SCANNERS=$((FAILED_SCANNERS + 1))
        echo "  [FAILED] Scanner exited with code $exit_code"
    fi

    if [ "$exit_code" -gt "$MAX_EXIT" ]; then
        MAX_EXIT=$exit_code
    fi

    # Count severity from output (supports both text and summary formats)
    # Text format: lines with [CRITICAL], [HIGH], [MEDIUM], [LOW]
    # Summary format: "scanner: N findings (XC YH ZM WL)"
    if [ "$FORMAT" = "summary" ]; then
        # Parse summary line: "scanner: N findings (29C 13H 0M 0L)"
        summary_line=$(grep -E '[0-9]+C [0-9]+H [0-9]+M [0-9]+L' "$out_file" 2>/dev/null || true)
        if [ -n "$summary_line" ]; then
            c_count=$(echo "$summary_line" | grep -oE '[0-9]+C' | grep -oE '[0-9]+')
            h_count=$(echo "$summary_line" | grep -oE '[0-9]+H' | grep -oE '[0-9]+')
            m_count=$(echo "$summary_line" | grep -oE '[0-9]+M' | grep -oE '[0-9]+')
            l_count=$(echo "$summary_line" | grep -oE '[0-9]+L' | grep -oE '[0-9]+')
        else
            c_count=0; h_count=0; m_count=0; l_count=0
        fi
    else
        c_count=$(grep -c '\[CRITICAL\]' "$out_file" 2>/dev/null || true)
        h_count=$(grep -c '\[HIGH\]' "$out_file" 2>/dev/null || true)
        m_count=$(grep -c '\[MEDIUM\]' "$out_file" 2>/dev/null || true)
        l_count=$(grep -c '\[LOW\]' "$out_file" 2>/dev/null || true)
    fi
    TOTAL_C=$((TOTAL_C + ${c_count:-0}))
    TOTAL_H=$((TOTAL_H + ${h_count:-0}))
    TOTAL_M=$((TOTAL_M + ${m_count:-0}))
    TOTAL_L=$((TOTAL_L + ${l_count:-0}))
done

echo ""
echo "=========================================="
TOTAL=$((TOTAL_C + TOTAL_H + TOTAL_M + TOTAL_L))
echo "  SCANNERS: $COMPLETED_SCANNERS/$EXPECTED_SCANNERS completed ($FAILED_SCANNERS failed)"
echo "  VERDICT: $TOTAL findings ($TOTAL_C critical, $TOTAL_H high, $TOTAL_M medium, $TOTAL_L low)"

# Exit code 3: infrastructure failure (scanners didn't run)
if [ "$COMPLETED_SCANNERS" -eq 0 ]; then
    echo "  EXIT CODE: 3 (no scanners completed — check configuration)"
    exit 3
elif [ "$FAILED_SCANNERS" -gt 0 ]; then
    echo "  WARNING: $FAILED_SCANNERS scanner(s) failed to run"
fi

if [ "$TOTAL_C" -gt 0 ]; then
    echo "  EXIT CODE: 2 (critical findings)"
    exit 2
elif [ "$TOTAL_H" -gt 0 ] || [ "$TOTAL_M" -gt 0 ]; then
    echo "  EXIT CODE: 1 (high/medium findings)"
    exit 1
else
    echo "  EXIT CODE: 0 (clean)"
    exit 0
fi
