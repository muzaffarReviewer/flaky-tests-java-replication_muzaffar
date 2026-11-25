#!/usr/bin/env bash
# Run ONE experimental condition: project x CPU limit x test-class order.
# Usage: scripts/run_condition.sh <project> <cpus> <fixed|random> <runs> <budget_minutes>
# Example: scripts/run_condition.sh java-websocket 0.5 random 100 300
set -u
PROJECT="$1"; CPUS="$2"; ORDER="$3"; RUNS="$4"; BUDGET_MIN="$5"
IMAGE="${IMAGE:-maven:3.9.9-eclipse-temurin-17}"
ROOT="$(pwd)"; WORK="$ROOT/work"; SRC="$WORK/$PROJECT"; M2="$WORK/m2"
RES="$ROOT/results"; LOGS="$ROOT/logs"
mkdir -p "$SRC" "$M2" "$RES" "$LOGS"

LINE="$(grep -E "^${PROJECT}," projects.csv)" || { echo "unknown project: $PROJECT"; exit 2; }
IFS=, read -r _NAME REPO COMMIT MVN_ARGS <<< "$LINE"

# 1. Fetch the pinned commit
cd "$SRC" || exit 2
git init -q
git remote add origin "https://github.com/${REPO}.git"
git fetch -q --depth 1 origin "$COMMIT" && git checkout -q FETCH_HEAD || { echo "checkout failed"; exit 2; }
cd "$ROOT" || exit 2

# 2. Record the environment (needed for reproducibility)
{
  echo "project=$PROJECT repo=$REPO commit=$COMMIT mvn_args=$MVN_ARGS"
  echo "cpus_limit=$CPUS order=$ORDER image=$IMAGE"
  echo "date=$(date -u +%FT%TZ)"
  echo "host_nproc=$(nproc)"
  grep -m1 'model name' /proc/cpuinfo
  grep -m1 MemTotal /proc/meminfo
  docker --version
} > "$RES/env.txt" 2>&1

# 3. Warm-up (network allowed, no CPU limit, NOT measured): downloads dependencies
# A hung warm-up is hard-killed after 15 min (SIGKILL; the container is then removed).
timeout -s KILL 15m docker run --name flaky_warm -v "$SRC":/work -v "$M2":/root/.m2 -w /work "$IMAGE" \
  mvn -B -ntp test $MVN_ARGS -Dmaven.test.failure.ignore=true > "$LOGS/warmup.log" 2>&1
echo "warm-up exit code: $? (137 = killed after 15 min)" >> "$RES/env.txt"
docker rm -f flaky_warm > /dev/null 2>&1

# 4. Measured runs (offline, CPU-limited container)
echo "project,cpus,order,run,seed,seconds,mvn_exit,test_cases" > "$RES/runs.csv"
START=$(date +%s)
for i in $(seq 1 "$RUNS"); do
  if (( ( $(date +%s) - START ) / 60 >= BUDGET_MIN )); then
    echo "time budget of ${BUDGET_MIN} min reached after $((i-1)) runs"; break
  fi
  SEED=$((1000 + i))   # same seeds in every CPU condition -> paired comparison
  if [[ "$ORDER" == "random" ]]; then
    ORDER_ARGS="-Dsurefire.runOrder=random -Dsurefire.runOrder.random.seed=$SEED"
  else
    ORDER_ARGS="-Dsurefire.runOrder=alphabetical"
  fi
  T0=$(date +%s.%N)
  # Per-run timeout (default 6 min): a hung run is hard-killed (SIGKILL) and discarded.
  # SIGKILL ends the docker client at once; the container is then removed below.
  timeout -s KILL "${RUN_TIMEOUT_MIN:-6}m" docker run --name flaky_run --cpus="$CPUS" -v "$SRC":/work -v "$M2":/root/.m2 -w /work "$IMAGE" sh -c \
    "find /work -type d -name surefire-reports -prune -exec rm -rf {} + ; \
     mvn -B -ntp -o test $MVN_ARGS $ORDER_ARGS -Dmaven.test.failure.ignore=true" \
    > "$LOGS/run_${i}.log" 2>&1
  RC=$?
  docker rm -f flaky_run > /dev/null 2>&1
  T1=$(date +%s.%N)
  SECS=$(python3 -c "print(round($T1 - $T0, 2))")
  if [[ "$RC" == "137" || "$RC" == "124" ]]; then
    RC=124   # normalised code for "timed out"
    N=0      # timed out: partial reports are discarded, not parsed
  else
    N=$(python3 scripts/parse_reports.py --src "$SRC" --project "$PROJECT" --cpus "$CPUS" \
          --order "$ORDER" --run "$i" --seed "$SEED" --out "$RES/tests.csv")
  fi
  echo "$PROJECT,$CPUS,$ORDER,$i,$SEED,$SECS,$RC,$N" >> "$RES/runs.csv"
  echo "run $i: ${SECS}s exit=$RC test_cases=$N"
done
gzip -f "$LOGS"/*.log 2>/dev/null
mkdir -p "$RES/logs" && mv "$LOGS"/*.gz "$RES/logs/" 2>/dev/null
exit 0
