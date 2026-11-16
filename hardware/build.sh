#!/usr/bin/env bash
# Build the KVM board in Docker.
#   ./build.sh            netlist + ERC, placed PCB, autoroute, DRC, renders, JLCPCB files
#                         (ROUTE_PARALLEL=6 routing attempts at once, see route_checked)
#   ./build.sh noroute    same, but stop before routing (placement only)
#   ./build.sh autoroute  one more autorouter pass on the current board
#   ./build.sh parts      re-import LCSC parts
#   ./build.sh shell      interactive shell in the toolchain
#   ./build.sh <target>   any Makefile target
set -euo pipefail
cd "$(dirname "$0")"
# One build at a time: two runs writing out/ at once corrupt each other.
exec 9>.build.lock
flock -n 9 || { echo "another build is running (.build.lock)" >&2; exit 1; }
IMAGE=kvm-board-tools
FR_VER=2.5.0
JAVA_IMAGE=eclipse-temurin:25.0.5_8-jre   # Freerouting 2.4 needs Java >= 25
FR_JAR=tools/freerouting-$FR_VER.jar
FR_PASSES=${FR_PASSES:-100}

# A registry hiccup shouldn't stop a build when the image is already here.
docker build -q -t "$IMAGE" . >/dev/null ||
  { docker image inspect "$IMAGE" >/dev/null && echo "docker build failed, using cached $IMAGE" >&2; }
# Run a command in the toolchain.  The container occasionally fails to exit
# after KiCad's Python finishes, so the deadline is enforced from the host and
# the (uniquely named) container is always force-removed afterwards.
KICAD_TIMEOUT=${KICAD_TIMEOUT:-900}
kicad() {
  # named per routing worker (WORKER) and subshell, so parallel attempts never
  # collide and a stopped worker's containers can be found and removed
  local name="kvmstep-${WORKER:-m}-$BASHPID-$RANDOM" rc=0
  timeout -k 10 "$KICAD_TIMEOUT" docker run --rm --init --name "$name" \
    -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work "$IMAGE" "$@" || rc=$?
  docker rm -f "$name" >/dev/null 2>&1 || true
  return $rc
}

# KiCad's Python bindings occasionally segfault or hang on exit.  Each step
# saves only when it has finished, so time-box it and retry until its
# success line shows.
step() {  # [STEP_TIMEOUT=s] step <success-regex> <script args...>
  # 600 s per try by default (steps run slower with several attempts going
  # at once); route_nets (~5 min alone) passes a longer STEP_TIMEOUT
  local ok=$1 out t=${STEP_TIMEOUT:-600}; shift
  for _ in 1 2 3; do
    out=$(KICAD_TIMEOUT=$((t + 60)) kicad timeout -k 10 "$t" python3 "$@" 2>&1 || true)
    if grep -qE "$ok" <<<"$out"; then grep -E "$ok" <<<"$out" | sed 's/.*destructor found\.//'; return; fi
    echo "  ($* crashed, retrying)"
  done
  echo "FAILED: $*"; echo "$out" | grep -v -i "debug\|leak" | tail -5; return 1
}

route() {
  [[ -f $FR_JAR ]] || { mkdir -p tools; curl -sL -o "$FR_JAR" \
    "https://github.com/freerouting/freerouting/releases/download/v$FR_VER/freerouting-$FR_VER.jar"; }
  step "skew"            hw/route_ss.py || return 1
  step "USB B"           hw/route_usb2.py || return 1
  step "pairs routed"    hw/route_pairs.py || return 1
  step "fanout:|neck"     hw/finish.py fanout || return 1
  STEP_TIMEOUT=1500 step "nets routed" hw/route_nets.py || return 1
  autoroute
}

# Freerouting on the current board: export, route, import, clean up, stitch.
# Run on a board that already carries autorouted wiring, it keeps that wiring
# as its starting point and only has to fit what is still open.
autoroute() {
  step "wrote .*dsn"      hw/route.py export || return 1
  # cap a run (FR_TIMEOUT s): an occasional optimisation pass takes 10+ minutes for nothing
  # The router itself is single-threaded: with several attempts running at
  # once, keep each JVM's GC to two threads and a bounded heap.
  timeout -k 10 "${FR_TIMEOUT:-1800}" docker run --rm --name "kvmfr-${WORKER:-m}-$BASHPID" \
    -u "$(id -u):$(id -g)" -v "$PWD:/work" -w /work/out/route "$JAVA_IMAGE" \
    java -XX:ActiveProcessorCount=2 -Xmx3g -jar "/work/$FR_JAR" -de kvm_board.dsn -do kvm_board.ses \
    -mp "$FR_PASSES" --gui.enabled=false \
    2>&1 | grep -E "stage completed" | sed 's/.*INFO *//' || true
  step "imported /work"   hw/route.py import || return 1
  step "routed:"          hw/route.py cleanup || return 1
  step "stitching vias"   hw/finish.py stitch || return 1
}

# Count unconnected items on the current board (KiCad DRC)
unconnected() {
  # kicad-cli occasionally hangs: give it 5 minutes, try twice, and report a
  # failed count as 99 (= "not done") rather than ending the whole build
  local n
  for _ in 1 2; do
    n=$(KICAD_TIMEOUT=360 kicad sh -c 'timeout -k 10 300 kicad-cli pcb drc --format json -o /tmp/d.json out/kvm_board.kicad_pcb >/dev/null 2>&1;
               python3 -c "import json; print(len(json.load(open(\"/tmp/d.json\"))[\"unconnected_items\"]))"' 2>/dev/null | tail -1) || true
    [[ $n =~ ^[0-9]+$ ]] && { echo "$n"; return; }
    echo "  (unconnected count failed, retrying)" >&2
  done
  echo 99
}

# One routing attempt from the placed board, with finishing passes while they
# close something: run in its own folder out/par/<k> (scripts, board, project
# files, Freerouting), so several attempts can run at once.  Writes the final
# count of unconnected items to out/par/<k>/result.
attempt_worker() {  # attempt_worker <k>
  local k=$1 d=out/par/$1
  rm -rf "$d"; mkdir -p "$d/out/route" "$d/hw" "$d/tools"
  cp hw/*.py hw/*.kicad_dru "$d/hw/"
  ln "$FR_JAR" "$d/$FR_JAR" 2>/dev/null || cp "$FR_JAR" "$d/$FR_JAR"
  cp out/route/placed.kicad_pcb "$d/out/kvm_board.kicad_pcb"
  cp out/kvm_board.kicad_pro out/kvm_board.kicad_dru "$d/out/"
  (
    cd "$d"; export WORKER="w$k"
    n=99
    if route; then
      n=$(unconnected | tail -1)
      echo "attempt $k: $n unconnected"
      # (up to 20 open and 5 passes: on the 102 mm board with its wide
      # trunks, 13 open came down to 7 in three passes)
      for pass in 1 2 3 4 5; do
        (( n > 0 && n <= 20 )) || break
        before=$n
        autoroute || break
        n=$(unconnected | tail -1)
        echo "attempt $k + finishing pass $pass: $n unconnected"
        (( n < before )) || break
      done
    else
      echo "attempt $k: crashed"
    fi
    echo "$n" > result
  ) > "$d/log" 2>&1
}

stop_worker() {  # stop_worker <k> <pid>: the worker and every container it started
  kill "$2" 2>/dev/null || true
  pkill -P "$2" 2>/dev/null || true
  docker ps -q --filter "name=kvmstep-w$1-" --filter "name=kvmfr-w$1-" | xargs -r docker rm -f >/dev/null 2>&1 || true
}

# Freerouting isn't deterministic: route the placed board ROUTE_PARALLEL times
# at once (default 6: one per physical core of an 8-core machine, two left
# for KiCad's own steps and the desktop).  The first attempt that reaches 0
# unconnected wins and the others are stopped; otherwise the best one is kept.
route_checked() {
  mkdir -p out/route
  cp out/kvm_board.kicad_pcb out/route/placed.kicad_pcb
  rm -rf out/par
  local P=${ROUTE_PARALLEL:-6} k pids=() done_=() best="" bestn=999 left
  for k in $(seq 1 "$P"); do
    attempt_worker "$k" & pids[k]=$!
    done_[k]=0
    sleep 15                        # stagger the KiCad steps a little
  done
  left=$P
  while (( left > 0 )); do
    sleep 10
    for k in $(seq 1 "$P"); do
      (( done_[k] )) && continue
      local d=out/par/$k
      if [[ -f $d/result ]] || ! kill -0 "${pids[k]}" 2>/dev/null; then
        wait "${pids[k]}" 2>/dev/null || true
        done_[k]=1; left=$((left - 1))
        grep -E "^attempt|FAILED" "$d/log" 2>/dev/null || true
        local n; n=$(cat "$d/result" 2>/dev/null || echo 99)
        [[ $n =~ ^[0-9]+$ ]] || n=99
        if (( n < bestn )); then bestn=$n; best=$k; fi
        if (( n == 0 )); then
          for j in $(seq 1 "$P"); do (( done_[j] )) || { stop_worker "$j" "${pids[j]}"; done_[j]=1; }; done
          left=0; break
        fi
      fi
    done
  done
  if [[ -n $best ]]; then
    cp "out/par/$best/out/kvm_board.kicad_pcb" out/kvm_board.kicad_pcb
    for k in $(seq 1 "$P"); do
      [[ -f out/par/$k/out/kvm_board.kicad_pcb ]] && cp "out/par/$k/out/kvm_board.kicad_pcb" "out/route/attempt_$k.kicad_pcb"
    done
  fi
  if (( bestn == 0 )); then
    echo "attempt $best won: 0 unconnected"
  else
    echo "WARNING: best attempt ($best) still has $bestn unconnected"
  fi
}

case "${1:-all}" in
  shell)   exec docker run --rm -it -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work "$IMAGE" bash ;;
  all)     kicad make pcb; route_checked; kicad make outputs ;;
  noroute) kicad make pcb outputs ;;
  # route the board in out/ as it is placed, without placing it again: the
  # routers follow the board file's footprint order, which a new placement
  # run may shuffle (same positions, different routing)
  reroute) route_checked; kicad make outputs ;;
  autoroute) autoroute; echo "$(unconnected | tail -1) unconnected" ;;   # one more pass on the board as it is
  *)       kicad make "$@" ;;
esac
