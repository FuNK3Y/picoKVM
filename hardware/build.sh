#!/usr/bin/env bash
# Build the KVM board in Docker.
#   ./build.sh            netlist + ERC, placed PCB, autoroute, DRC, renders, JLCPCB files
#   ./build.sh noroute    same, but stop before routing (placement only)
#   ./build.sh parts      re-import LCSC parts
#   ./build.sh shell      interactive shell in the toolchain
#   ./build.sh <target>   any Makefile target
set -euo pipefail
cd "$(dirname "$0")"
# One build at a time: two runs writing out/ at once corrupt each other.
exec 9>.build.lock
flock -n 9 || { echo "another build is running (.build.lock)" >&2; exit 1; }
IMAGE=kvm-board-tools
FR_VER=2.4.1
JAVA_IMAGE=eclipse-temurin:25.0.4.1_1-jre   # Freerouting 2.4 needs Java >= 25
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
  local name="kvmstep-$$-$RANDOM" rc=0
  timeout -k 10 "$KICAD_TIMEOUT" docker run --rm --init --name "$name" \
    -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work "$IMAGE" "$@" || rc=$?
  docker rm -f "$name" >/dev/null 2>&1 || true
  return $rc
}

# KiCad's Python bindings occasionally segfault or hang on exit.  Each step
# saves only when it has finished, so time-box it and retry until its
# success line shows.
step() {  # step <success-regex> <script args...>
  local ok=$1 out; shift
  for _ in 1 2 3; do
    out=$(KICAD_TIMEOUT=360 kicad timeout -k 10 300 python3 "$@" 2>&1 || true)
    if grep -qE "$ok" <<<"$out"; then grep -E "$ok" <<<"$out" | sed 's/.*destructor found\.//'; return; fi
    echo "  ($* crashed, retrying)"
  done
  echo "FAILED: $*"; echo "$out" | grep -v -i "debug\|leak" | tail -5; return 1
}

route() {
  [[ -f $FR_JAR ]] || { mkdir -p tools; curl -sL -o "$FR_JAR" \
    "https://github.com/freerouting/freerouting/releases/download/v$FR_VER/freerouting-$FR_VER.jar"; }
  step "skew"            hw/route_ss.py || return 1
  step "peripheral"      hw/route_usb2.py || return 1
  step "fanout:|neck"     hw/finish.py fanout || return 1
  autoroute
}

# Freerouting on the current board: export, route, import, clean up, stitch.
# Run on a board that already carries autorouted wiring, it keeps that wiring
# as its starting point and only has to fit what is still open.
autoroute() {
  step "wrote .*dsn"      hw/route.py export || return 1
  # cap a run: an occasional optimisation pass takes 10+ minutes for nothing
  timeout -k 10 900 docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work" -w /work/out/route "$JAVA_IMAGE" \
    java -jar "/work/$FR_JAR" -de kvm_board.dsn -do kvm_board.ses -mp "$FR_PASSES" --gui.enabled=false \
    2>&1 | grep -E "stage completed" | sed 's/.*INFO *//' || true
  step "imported /work"   hw/route.py import || return 1
  step "routed:"          hw/route.py cleanup || return 1
  step "stitching vias"   hw/finish.py stitch || return 1
}

# Count unconnected items on the current board (KiCad DRC)
unconnected() {
  # kicad-cli occasionally hangs: give it 5 minutes
  kicad sh -c 'timeout -k 10 300 kicad-cli pcb drc --format json -o /tmp/d.json out/kvm_board.kicad_pcb >/dev/null 2>&1;
               python3 -c "import json; print(len(json.load(open(\"/tmp/d.json\"))[\"unconnected_items\"]))"'
}

# Freerouting isn't deterministic and occasionally leaves a fine-pitch pin
# open: route from the placed board, and retry if KiCad's DRC disagrees.
route_checked() {
  mkdir -p out/route
  cp out/kvm_board.kicad_pcb out/route/placed.kicad_pcb
  # the autorouter is randomised: with tight rules some runs leave a wide
  # power track unrouted, so give it several tries from the same placement
  for attempt in $(seq 1 "${ROUTE_ATTEMPTS:-6}"); do
    cp out/route/placed.kicad_pcb out/kvm_board.kicad_pcb
    # a KiCad crash that survives step()'s retries fails this attempt only
    route || { echo "attempt $attempt: crashed"; continue; }
    local n; n=$(unconnected | tail -1)
    echo "attempt $attempt: $n unconnected"
    [[ $n == 0 ]] && return
    # a few open connections: one finishing pass from this result
    if (( n <= 6 )) && autoroute; then
      n=$(unconnected | tail -1)
      echo "attempt $attempt + finishing pass: $n unconnected"
      [[ $n == 0 ]] && return
    fi
  done
  echo "WARNING: still $n unconnected after ${ROUTE_ATTEMPTS:-6} attempts"
}

case "${1:-all}" in
  shell)   exec docker run --rm -it -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/work" -w /work "$IMAGE" bash ;;
  all)     kicad make pcb; route_checked; kicad make outputs ;;
  noroute) kicad make pcb outputs ;;
  *)       kicad make "$@" ;;
esac
