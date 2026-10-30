#!/usr/bin/env bash
# Full-profile evalnoise study and Monte Carlo validation (CPU only, no model calls).
# Resumable: finished units/shards are skipped on rerun. Up to 3 attempts per stage.
# Progress: tmp/longrun.log (plus each stage's progress.log).
# Smoke test on a tiny slice: LONGRUN_SMOKE=1 bash scripts/longrun.sh
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p tmp
LOG=tmp/longrun.log
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$LOG"; }

STUDY_ONLY=()
VALIDATE_ONLY=()
if [ "${LONGRUN_SMOKE:-0}" = "1" ]; then
  STUDY_ONLY=(--only ruleproof-pressure)
  VALIDATE_ONLY=(--only naive-t30-r1)
fi

run_stage() {
  local name="$1"; shift
  local attempt
  for attempt in 1 2 3; do
    log "$name: attempt $attempt: $*"
    local rc=0
    "$@" >>"$LOG" 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
      log "$name: ok"
      return 0
    fi
    log "$name: failed (exit $rc)"
    sleep 10
  done
  log "$name: giving up after 3 attempts"
  return 1
}

# ${arr[@]+...}: bash < 4.4 treats an empty array as unset under set -u.
log "start (smoke=${LONGRUN_SMOKE:-0})"
run_stage study uv run evalnoise study --profile full --out results/study-full ${STUDY_ONLY[@]+"${STUDY_ONLY[@]}"} || exit 1
run_stage validate uv run evalnoise validate --profile full --out results/validation-full ${VALIDATE_ONLY[@]+"${VALIDATE_ONLY[@]}"} || exit 1
log "done"
