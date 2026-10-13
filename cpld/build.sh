#!/usr/bin/env bash
# Build the two ATF1502AS of SolderDemon m68k Really Simple Video: rsv_u?.pld -> bin/rsv_u?.jed
#
# Uses the WinCUPL + Atmel fitter docker image (see ../../tools/cpld-toolchain), then checks
#   1. that the fitter kept every pin where the .pld puts it -- the board is routed to those pins;
#   2. that the fitted equations behave like tools/cupl.py's model, which sim_card.py ran.
#
#   ./build.sh            (needs a running docker)
#
# Program over JTAG on J3 (chain TDI -> U1 -> U2 -> TDO): rsv_u1.jed into U1, rsv_u2.jed into U2.
set -euo pipefail
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1
IMAGE=${CPLD_IMAGE:-dinoboards/cpld-toolchain:latest}
HOSTDIR=$(pwd -W 2>/dev/null || pwd)

rm -rf bin
for f in rsv_u1 rsv_u2; do
    docker run --rm -v "$HOSTDIR:/work" "$IMAGE" cupld "$f" > /dev/null 2>&1 || true
    [ -f "bin/$f.jed" ] || { echo "$f: no .jed, see bin/$f.fit"; exit 1; }
    python - "$f" <<'EOF'
import re, sys
sys.path.insert(0, '../tools')
import cupl
f = sys.argv[1]
want = {name: n for n, name in cupl.Device(open(f + '.pld', encoding='utf-8').read()).pins.items()}
fit = open('bin/' + f + '.fit', encoding='latin-1').read()
assert re.search(r'^\$Device \S+ fits;', fit, flags=re.M), f'{f}: does not fit'
got = {s: int(n) for n, s in re.findall(r'^Pin (\d+)\s*=\s*(\w+);', fit, flags=re.M)}
bad = {s: (n, got.get(s)) for s, n in want.items() if got.get(s) != n}
assert not bad, f'{f}: fitter moved pins {bad}'
used = re.search(r'Total Macro cells used\s+(\S+)', fit).group(1)
print(f'{f}: {len(want)} pins as assigned, {used} macrocells')
EOF
done
python ../tools/check_fit.py rsv_u1 rsv_u2
