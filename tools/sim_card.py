"""Zero-delay logic simulation of the generated netlist (design.json + symbol pin names).

Every IC is modelled by its function and wired exactly as build_card.py wired it, so wrong pins,
swapped polarities and decode mistakes show up here before they reach copper. The two ATF1502AS
run the equations in code/firmware/cpld/rsv_u1.pld and code/firmware/cpld/rsv_u2.pld, read and evaluated by tools/cupl.py, on
the pins declared there. Checks:
  * the byte counter (U1) and the line counter (U2) run their full cycles and recover from every
    power-up state;
  * the split address multiplexer: MA0..MA16 is the video address during display and the CPU
    address during a card cycle -- the two halves live in different chips;
  * raster: 100 bytes x 800 clocks x 525 lines, HSYNC/VSYNC position and width, blanking;
  * CPU cycles through J1: VRAM write/read on both pages, register write, status read, /DTACK,
    no data-bus contention, SRAM /WE only for VRAM writes;
  * picture: all 307200 pixels of a frame compared against the SRAM, plus a pass after a flip.
It proves logic, not timing, and it cannot prove that the Atmel fitter will place either half --
only WinCUPL can. Run with any Python 3: writes sim-verification.txt.
"""
from pathlib import Path
import json, sys
from collections import defaultdict, deque

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
import videolib as g
import cupl

LIBNAME = 'SolderDemonReallySimpleVideo'
PLD = {'U1': (ROOT / 'code' / 'firmware' / 'cpld' / 'rsv_u1.pld').read_text(encoding='utf-8'),
       'U2': (ROOT / 'code' / 'firmware' / 'cpld' / 'rsv_u2.pld').read_text(encoding='utf-8')}
parts = json.loads((ROOT / 'design' / 'design.json').read_text())
local = g.parse((ROOT / 'design' / f'{LIBNAME}.kicad_sym').read_text(encoding='utf-8'))


def pin_names(key):
    lib, name = key.split(':')
    sym = next(s for s in g.sub(local, 'symbol') if s[1] == name) if lib == LIBNAME else g.library_symbol(lib, name)
    out = {}
    for u in g.sub(sym, 'symbol'):
        for p in g.sub(u, 'pin'):
            out[str(g.one(p, 'number')[1])] = str(g.one(p, 'name')[1])
    return out


# ---- nets ----------------------------------------------------------------------------------
val = defaultdict(int)           # resolved net levels (0/1); undriven nets read 1 (pull-up/float high)
drivers = defaultdict(dict)      # net -> {driver id: 0/1/None}
readers = defaultdict(list)
contention = []
val['+5V'] = 1
val['GND'] = 0


def resolve(net):
    act = [x for x in drivers[net].values() if x is not None]
    if len(set(act)) > 1:
        contention.append((net, dict(drivers[net])))
    if net == '~{DTACK}':                      # open drain with the mainboard pull-up
        return 0 if 0 in act else 1
    return act[0] if act else 1


class Part:
    def __init__(self, p):
        self.ref, self.value = p['ref'], p['value']
        names = pin_names(p['key'])
        self.n = {names[num]: net for num, net in p['nets'].items() if net}
        for net in self.n.values():
            readers[net].append(self)

    def get(self, name, snap=None):
        net = self.n.get(name)
        if net is None:
            raise KeyError(f'{self.ref}.{name} not connected')
        return (snap if snap is not None else val)[net]

    def drive_net(self, net, v, changed):
        if net is None or net in ('+5V', 'GND'):
            return
        if drivers[net].get(self.ref, 'x') == v:
            return
        drivers[net][self.ref] = v
        nv = resolve(net)
        if nv != val[net]:
            val[net] = nv
            changed.append(net)

    def drive(self, name, v, changed):
        self.drive_net(self.n.get(name), v, changed)


class Xcvr245(Part):
    def eval(self, ch, snap):
        on, a2b = not self.get('CE'), self.get('A->B')
        for i in range(8):
            self.drive(f'B{i}', self.get(f'A{i}') if on and a2b else None, ch)
            self.drive(f'A{i}', self.get(f'B{i}') if on and not a2b else None, ch)


class Sram(Part):
    BITS = 17

    def __init__(self, p):
        super().__init__(p)
        self.mem = bytearray(1 << self.BITS)
        self.writes = 0

    def eval(self, ch, snap):
        a = sum(self.get(f'A{i}') << i for i in range(self.BITS))
        ce = self.get('~{CS1}/~{CE1}') or not self.get('CS2/CE2')
        oe, we = self.get('~{OE}'), self.get('~{WE}')
        if not ce and not we:
            self.mem[a] = sum(self.get(f'DQ{i}') << i for i in range(8))
            self.writes += 1
        out = not ce and not oe and we
        for i in range(8):
            self.drive(f'DQ{i}', self.mem[a] >> i & 1 if out else None, ch)


class Shift166(Part):
    """74HC166: PE low loads A..H on the rising edge, otherwise shifts Ds into QA and QG into QH."""
    def __init__(self, p):
        super().__init__(p)
        self.last = None
        self.q = [0] * 8

    def eval(self, ch, snap):
        c = self.get('Clk')
        if self.last is not None and c and not self.last and not self.get('CE', snap):
            if not self.get('PE', snap):
                self.q = [self.get(x, snap) for x in 'ABCDEFGH']
            else:
                self.q = [self.get('Ds', snap)] + self.q[:7]
        self.last = c
        if not self.get('Clr'):
            self.q = [0] * 8
        self.drive('Qh', self.q[7], ch)


class Cpld(Part):
    """ATF1502AS running the equations in its own .pld on the pins declared there."""
    def __init__(self, p):
        self.ref, self.value = p['ref'], p['value']
        self.dev = cupl.Device(PLD[self.ref])
        # design.json keys the CPLD by pin number; map the .pld signal names onto nets.
        self.sig = {self.dev.pins[int(num)]: net for num, net in p['nets'].items()
                    if net and int(num) in self.dev.pins}
        assert len(self.sig) == len(self.dev.pins), sorted(set(self.dev.pins.values()) - set(self.sig))
        for net in set(self.sig.values()):
            readers[net].append(self)
        self.q = self.dev.reset_state()
        self.last = None

    def levels(self, src):
        return {name: src[net] for name, net in self.sig.items()}

    def eval(self, ch, snap):
        c = val[self.sig['CLK25']]
        if self.last is not None and c and not self.last:
            self.q = self.dev.clock_edge(self.levels(snap), self.q)
        self.last = c
        for name, v in self.dev.outputs(self.levels(val), self.q).items():
            self.drive_net(self.sig[name], v, ch)


MODELS = {'74HCT245': Xcvr245, 'AS6C1008-55PCN': Sram, '74HC166': Shift166,
          'ATF1502AS-10JU44': Cpld}
P = {}
for p in parts:
    cls = MODELS.get(p['value'])
    if cls:
        P[p['ref']] = cls(p)
assert len([r for r in P if r.startswith('U')]) == 5, sorted(P)
sram = P['U3']
u1, u2 = P['U1'], P['U2']
CPU = 'J1'

# X1 pin 5 reaches its loads through the series resistors R7 (CPLDs) and R8 (U5): a zero-delay
# model treats each resistor as a wire, so X1 drives every net on the far side of one too.
x1 = next(p for p in parts if p['ref'] == 'X1')['nets']['5']
CLOCKS = [x1] + [n for p in parts if p['ref'].startswith('R')
                 for a, n in ((p['nets']['1'], p['nets']['2']), (p['nets']['2'], p['nets']['1'])) if a == x1]
assert sorted(CLOCKS[1:]) == ['CLK25', 'CLK_SR'], CLOCKS
assert u1.sig['CLK25'] == u2.sig['CLK25'] == 'CLK25' and P['U5'].n['Clk'] == 'CLK_SR'


def settle(snap, start=None):
    queue = deque(P.values() if start is None else start)
    queued = set(queue)
    guard = 0
    while queue:
        guard += 1
        assert guard < 200000, 'combinational loop'
        part = queue.popleft()
        queued.discard(part)
        ch = []
        part.eval(ch, snap)
        for net in ch:
            for r in readers[net]:
                if r not in queued:
                    queue.append(r)
                    queued.add(r)


def cpu(**sig):
    """Drive J1 nets (None releases a bus line) and settle."""
    snap = dict(val)
    start = set()
    for net, v in sig.items():
        net = {'EXPSEL': '~{EXPSEL}', 'LDS': '~{LDS}', 'RESET': '~{RESET}'}.get(net, net)
        drivers[net][CPU] = v
        val[net] = resolve(net)
        start.update(readers[net])
    settle(snap, start)


def set_addr(a):
    cpu(**{f'A{i}': a >> i & 1 for i in range(1, 24)})


TICKS = 0


def tick():
    global TICKS
    TICKS += 1
    snap = dict(val)
    start = {}
    for net in CLOCKS:
        drivers[net]['X1'] = 1 - val[net]
        val[net] = resolve(net)
        start.update(dict.fromkeys(readers[net]))
    settle(snap, start)


def expsel(a):
    """SolderDemon m68k (rosco_m68k r2) mainboard PLD: /EXPSEL = /AS * (A23*/A21 + /A23*A22 + /A23*A20 + /A22*A21)."""
    b = lambda n: a >> n & 1
    return 0 if (b(23) and not b(21)) or (not b(23) and b(22)) or (not b(23) and b(20)) or (not b(22) and b(21)) else 1


LAST = {}


def cycle(a, data=None):
    """One 68010 byte cycle: address + R/W, then AS (-> /EXPSEL), data, /LDS; returns (dtack, byte).

    /LDS is held for four CLK25 cycles, which is about what a 10 MHz 68010 does and is long
    enough for the CPLDs to let the 74HCT245 on and to sample a register write.
    """
    rw = 1 if data is None else 0
    assert a & 1, 'byte cycles on odd addresses use /LDS'
    set_addr(a)
    cpu(RWB=rw)
    cpu(EXPSEL=expsel(a))
    if data is not None:
        cpu(**{f'D{i}': data >> i & 1 for i in range(8)})
    tick(); tick()                                   # video keeps running during the cycle
    cpu(LDS=0)
    for _ in range(8):
        tick()
    dtack = val['~{DTACK}'] == 0
    got = sum(val[f'D{i}'] << i for i in range(8))
    LAST.update(vbl=val['VBLANK'], hbl=u1.q['HBLANK'],
                drv={r for i in range(8) for r, x in drivers[f'D{i}'].items() if x is not None and r != CPU})
    cpu(LDS=1)
    cpu(EXPSEL=1)
    tick()
    cpu(RWB=1, **{f'D{i}': None for i in range(8)})
    return dtack, (got if rw else None)


log = []


def check(cond, msg):
    log.append(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        print('FAIL', msg)


# ---- the two counters on their own -----------------------------------------------------------
def counter(which, prefix, width, modulus, force):
    """Step one counter directly: `force` puts the device where the next edge is that counter's
    enable, so one clock_edge is one count. Returns (full cycle seen, worst recovery)."""
    dev = cupl.Device(PLD[which])
    idle = {n: 1 if n in ('RESET_N', 'LDS_N', 'EXPSEL_N', 'RW') else 0 for n in dev.pins.values()}
    q = dev.reset_state()
    value = lambda: sum(q[f'{prefix}{i}'] << i for i in range(width))
    seq = []
    for _ in range(modulus + 1):
        seq.append(value())
        q = dev.clock_edge(force(idle, q), q)
    worst = 0
    for start in range(1 << width):
        q = dev.reset_state()
        for i in range(width):
            q[f'{prefix}{i}'] = start >> i & 1
        for steps in range(2 * modulus):
            if value() == 0:
                break
            q = dev.clock_edge(force(idle, q), q)
        else:
            return False, start
        worst = max(worst, steps)
    return seq == list(range(modulus)) + [0], worst


def at_byte_end(idle, q):
    q['PH0'] = q['PH1'] = q['PH2'] = 1                   # U1: the byte counter steps on this edge
    return idle


def at_line_end(idle, q):
    return {**idle, 'LEND': 1}                           # U2: LEND is an input pin


ok, worst = counter('U1', 'B', 7, 100, at_byte_end)
check(ok and worst < 100, f'U1 byte counter runs 0..99 and reaches 0 from all 128 power-up states (worst {worst} steps)')
ok, worst = counter('U2', 'L', 10, 525, at_line_end)
check(ok and worst < 525, f'U2 line counter runs 0..524 and reaches 0 from all 1024 power-up states (worst {worst} steps)')

# ---- power-on ---------------------------------------------------------------------------------
for net in CLOCKS:
    drivers[net]['X1'] = 0
    val[net] = 0
cpu(EXPSEL=1, LDS=1, RWB=1, RESET=0, **{f'A{i}': 0 for i in range(1, 24)})
settle(dict(val))
tick(); tick()
cpu(RESET=1)
check(u1.q['VIDEOON'] == 0 and u2.q['PAGE'] == 0, 'system reset clears both halves of the control register')
for _ in range(16):
    tick()
check(val['PIXEL'] == 0, 'video off: no pixels leave the 74HC166')

# ---- CPU access -------------------------------------------------------------------------------
BASE = 0xA00000
REG = 0xB00001


def vaddr(page, x, y):
    return BASE + 1 + 2 * (page << 16 | y << 7 | x >> 3)


dt, _ = cycle(REG, 0x01)
check(dt, 'register write acknowledged')
check(u1.q['VIDEOON'] == 1 and u2.q['PAGE'] == 0, 'control register b0 = video on (U1), b1 = page (U2)')
dt, _ = cycle(REG, 0x03)
check(u2.q['PAGE'] == 1, 'b1 selects page 1')
cycle(REG, 0x01)
w = sram.writes
dt, st = cycle(REG)
check(dt and (st & 1) == LAST['vbl'] and (st >> 1 & 1) == LAST['hbl'] and LAST['drv'] == {'U1'},
      f'status read: b0 = VBLANK, b1 = HBLANK, driven only by U1 (read {st:#04x})')
dt, _ = cycle(0xBFFFFF, 0x01)
check(dt and u1.q['VIDEOON'] == 1, 'the register repeats up to $BFFFFF')
check(sram.writes == w, 'register cycles never write the SRAM')

import random
random.seed(1502)
pattern = {}
for page in (0, 1):
    for y, x in [(0, 0), (479, 632)] + [(random.randrange(480), random.randrange(80) * 8) for _ in range(10)]:
        pattern[(page, x, y)] = random.randrange(256)
acks = sum(cycle(vaddr(p, x, y), c)[0] for (p, x, y), c in pattern.items())
check(acks == len(pattern), f'{len(pattern)} VRAM writes on both pages acknowledged')
check(all(sram.mem[p << 16 | y << 7 | x >> 3] == c for (p, x, y), c in pattern.items()),
      'each byte landed in SRAM cell page << 16 | y << 7 | x >> 3 -- the two address halves agree')
ok = True
for (page, x, y), c in pattern.items():
    dt, got = cycle(vaddr(page, x, y))
    ok &= dt and got == c
check(ok, 'every byte reads back through the 74HCT245')
for a in (0x900001, 0xC00001, 0xF40001, 0x000001):
    dt, _ = cycle(a)
    check(not dt, f'no /DTACK outside $A00000-$BFFFFF (${a:06X})')
w = sram.writes
cycle(0x900001, 0x55)
check(sram.writes == w, 'writes outside the window leave the SRAM alone')
bus = [c for c in contention if c[0].startswith(('D', 'MD'))]
check(not bus, f'no contention on D0-D7 / MD0-MD7 during CPU cycles ({len(bus)} events)')

# ---- fill both pages with a deterministic picture ----------------------------------------------
for page in (0, 1):
    for y in range(480):
        seed = (page * 7919 + y * 31) & 0xFF
        for bx in range(80):
            sram.mem[page << 16 | y << 7 | bx] = (seed ^ (bx * 37 + y)) & 0xFF

# ---- raster + picture --------------------------------------------------------------------------
B = lambda: sum(u1.q[f'B{i}'] << i for i in range(7))
L = lambda: sum(u2.q[f'L{i}'] << i for i in range(10))
PH = lambda: u1.q['PH0'] | u1.q['PH1'] << 1 | u1.q['PH2'] << 2
MA = lambda: sum(val[f'MA{i}'] << i for i in range(17))

cycle(REG, 0x01)                                     # video on, page 0
while not (L() == 0 and B() == 0 and PH() == 0 and val['CLK25'] == 1):
    tick()
check(L() == 0 and B() == 0, 'counters reach byte 0 of line 0')


def scan(page, lines, want_raster=False):
    """Walk `lines` raster lines from the current position, comparing every pixel with the SRAM."""
    bad, lit, ma_bad, hs_fall, hs_run, hs_widths, vs_lines, line_len, mark = [], [], 0, [], 0, set(), set(), set(), None
    prev_hs = val['~{HSYNC}']
    for _ in range(lines * 800):
        tick()                                       # rising edge: new pixel, new B/PH
        b, ph, l, pix, hs = B(), PH(), L(), val['PIXEL'], val['~{HSYNC}']
        # MA7..MA15 carries L0..L8 only: during lines 512..524 -- deep in vertical blanking,
        # where nothing is fetched -- the row field is L mod 512, which is what the card does.
        if MA() != (page << 16 | (l & 0x1FF) << 7 | b):
            ma_bad += 1
        c = b * 8 + ph
        if 8 <= c <= 647 and l < 480:
            x = c - 8
            byte = sram.mem[page << 16 | l << 7 | (x >> 3)]
            if pix != (byte >> (7 - (x & 7)) & 1) and len(bad) < 5:
                bad.append((l, x, pix))
        elif pix and len(lit) < 5:
            lit.append((l, c, pix))
        if want_raster:
            if hs == 0:
                hs_run += 1
            if hs == 0 and prev_hs == 1:
                hs_fall.append((TICKS, c))
                if mark is not None:
                    line_len.add((TICKS - mark) // 2)
                mark = TICKS
            if hs == 1 and prev_hs == 0:
                hs_widths.add(hs_run)
                hs_run = 0
            if val['~{VSYNC}'] == 0:
                vs_lines.add(l)
            prev_hs = hs
        tick()                                       # falling edge
    return bad, lit, ma_bad, hs_fall, hs_widths, vs_lines, line_len


bad, lit, ma_bad, hs_fall, hs_widths, vs_lines, line_len = scan(0, 525, want_raster=True)
check(line_len == {800}, f'line = 800 clocks of 25.000 MHz = 31.250 kHz (measured {sorted(line_len)})')
check(len(hs_fall) == 525, f'525 lines per frame = 59.52 Hz (measured {len(hs_fall)})')
check({c for _, c in hs_fall} == {83 * 8}, f'HSYNC falls at clock 664 of the line, 16 clocks of front porch after pixel 639 (measured {sorted({c for _, c in hs_fall})})')
check(hs_widths == {96}, f'HSYNC is 96 clocks = 3.84 us (measured {sorted(hs_widths)})')
check(vs_lines <= {490, 491, 492} and {490, 491} <= vs_lines,
      f'VSYNC covers lines 490-491 (measured {sorted(vs_lines)}; it is released one 25 MHz clock into 492)')
check(ma_bad == 0, f'MA0..MA16 is the video address on every clock of the frame -- U1 low half, U2 high half ({ma_bad} mismatches)')
check(not bad, f'all 307200 pixels of page 0 match the SRAM, bit 7 leftmost {bad[:3]}')
check(not lit, f'the pixel line is 0 outside the 640 x 480 picture {lit[:3]}')

# ---- page flip ---------------------------------------------------------------------------------
while L() < 485:
    tick(); tick()
cycle(REG, 0x03)                                     # video on, page 1, inside vertical blanking
check(u2.q['PAGE'] == 1, 'page flipped inside vertical blanking')
while not (L() == 0 and B() == 0 and PH() == 0 and val['CLK25'] == 1):
    tick()
bad, lit, ma_bad = scan(1, 4)[:3]
check(not bad and not lit and ma_bad == 0, f'after the flip the first 4 lines come from page 1 {bad[:3]}{lit[:3]}')

bus = [c for c in contention if c[0].startswith(('D', 'MD'))]
check(not bus, f'no bus contention anywhere in the run ({len(bus)} events)')

out = '\n'.join(log) + f"\n\n{sum(x.startswith('PASS') for x in log)} passed, {sum(x.startswith('FAIL') for x in log)} failed\n"
(ROOT / 'sim-verification.txt').write_text(out)
print(out)
sys.exit(1 if 'FAIL' in out else 0)
