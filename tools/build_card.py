"""SolderDemon m68k Really Simple Video r1: schematic + PCB placement generator. Run with KiCad 10 python.

VGA framebuffer card: 640 x 480, 1 bit per pixel, 2 pages, 5 ICs.

The logic is two ATF1502AS-10JU44 (PLCC-44). Their equations and their pinouts come from
cpld/rsv_u1.pld and cpld/rsv_u2.pld, which this script reads -- moving a signal to another pin is
a one-line change there and the schematic follows.
  U1 bus interface, byte counter B = 0..99, HSYNC, HBLANK, the low address half MA0..MA6,
     the control register bit "video on" and the status read;
  U2 line counter L = 0..524, VSYNC, VBLANK, the high address half MA7..MA16 and the page bit.
Splitting the counters along with the multiplexer halves keeps the address multiplexer inside
the CPLDs: no counter bit crosses between the chips, only SEL_N, LEND and VBLANK.
Memory: one AS6C1008 (128K) holds 2 pages of 480 x 128 bytes: address = page:L[8:0]:B[6:0].
A 74HC166 turns the byte into eight pixels; Q1 buffers the bit and three resistors take it to R, G and B.
VRAM at odd addresses $A00001 + 2n, control and status at $B00001.
"""
from pathlib import Path
import subprocess, sys, xml.etree.ElementTree as ET
import videolib as g
import cupl
import pcbnew as pcb

ROOT = Path(__file__).resolve().parents[1]
CLI = 'C:/Program Files/KiCad/10.0/bin/kicad-cli.exe'
g.LIB = Path('C:/Program Files/KiCad/10.0/share/kicad')
NAME = 'solderdemon_m68k-realy-simple-video-card'
BASE = 0xA00000          # decoded in cpld/rsv_u1.pld; only used for notes and silkscreen here
REG = 0xB00001
REV = 'r1'
W, H = 92.0, 96.0

d = g.Design(NAME, 'SolderDemon m68k Really Simple Video / VGA 640x480 mono, 2x ATF1502AS + SRAM', REV,
             '2026-09-20', paper='A2', libname='SolderDemonReallySimpleVideo', ns='solderdemon-really-simple-video-r1/')
DIP = lambda n, w=7.62: f'Package_DIP:DIP-{n}_W{w:.2f}mm_Socket_LongPads'
FP_PLCC = 'Package_LCC:PLCC-44_THT-Socket'
FP_C = 'Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm'
FP_CP = 'Capacitor_THT:CP_Radial_D6.3mm_P2.50mm'
FP_R = 'Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal'
FP_BUS = 'SolderDemonReallySimpleVideo:PinSocket_2x32_P2.54mm_Horizontal_CardEdge'
FP_VGA = 'SolderDemonReallySimpleVideo:DSUB-15-HD_Socket_Horizontal_P2.29x1.90mm_EdgePinOffset3.03mm_Housed_MountingHolesOffset4.94mm'
FP_OSC = 'Oscillator:Oscillator_DIP-8'
FP_JTAG = 'Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical'
LOCAL_FP = ROOT / 'SolderDemonReallySimpleVideo.pretty'

# ---- ATF1502AS PLCC-44 package: the pins the .pld cannot describe ----------------------------
# The 44-lead pinout the whole ATF150x/MAX7000 family shares. Pins 1, 2, 43 and 44 are the
# dedicated inputs (GCLR, OE2/GCLK2, GCLK1, OE1) and are assigned in the .pld like any other.
VCC_PINS = (3, 15, 23, 35)
GND_PINS = (10, 22, 30, 42)
JTAG_PINS = {7: 'TDI', 13: 'TMS', 32: 'TCK', 38: 'TDO'}


def named(key, m):
    """Map pins by name; every name in the symbol must be listed (None = no-connect)."""
    pins = {}
    for p in d._pins(key):
        pins[g.one(p, 'name')[1]] = (g.one(p, 'number')[1], p[1])
    assert set(m) == set(pins), (key, 'unknown', set(m) - set(pins), 'missing', set(pins) - set(m))
    for name, (num, typ) in pins.items():
        assert m[name] or typ not in ('input', 'power_in'), f'{key}: input {name} left open'
    return {num: m[name] for name, (num, typ) in pins.items()}


# ---- J1: SolderDemon m68k expansion bus (JP3 pinout, same as rosco_m68k r2) -
bus = {1 + 2 * i: f'A{i + 1}' for i in range(23)}
bus.update({2: '+5V', 4: 'CLK', 6: 'GND', 8: '~{VPA}', 10: 'E', 12: '~{VMA}', 14: '~{IRQ3}', 16: '~{IOSEL}', 18: '~{EXPSEL}',
            20: 'FC0', 22: 'FC1', 24: 'FC2', 26: '~{IRQ5}', 28: '~{IRQ2}', 30: '~{IRQ6}', 32: '~{LDS}', 34: '~{UDS}', 36: '~{RESET}',
            47: '~{AS}', 49: '~{BERR}', 51: '~{BG}', 53: '~{BGACK}', 55: '~{BR}', 57: '~{DTACK}', 59: 'RWB', 61: 'D0', 63: 'D1'})
bus.update({38 + 2 * i: f'D{15 - i}' for i in range(14)})
used = ({'+5V', 'GND', '~{EXPSEL}', '~{LDS}', '~{RESET}', '~{DTACK}', 'RWB'}
        | {f'A{i}' for i in list(range(1, 18)) + [20, 21, 23]} | {f'D{i}' for i in range(8)})
k = d.custom('BUS_2x32', [(i, bus[i], 'passive') for i in range(1, 65, 2)], [(i, bus[i], 'passive') for i in range(2, 65, 2)], FP_BUS, ref='J')
d.add('J1', k, 'SOLDERDEMON M68K BUS', {i: n if n in used else None for i, n in bus.items()}, (40, 110))

# ---- U1, U2: the two ATF1502AS. Pin numbers and directions come from the CUPL sources --------
NET = {'LDS_N': '~{LDS}', 'EXPSEL_N': '~{EXPSEL}', 'RESET_N': '~{RESET}', 'RW': 'RWB', 'DTACK_N': '~{DTACK}',
       'SEL_N': '~{SEL}', 'SRAM_WE_N': '~{SRAM_WE}', 'BUF_OE_N': '~{BUF_OE}', 'LOAD_N': '~{LOAD}',
       'HSYNC_N': '~{HSYNC}', 'VSYNC_N': '~{VSYNC}'}
DEV = {}
for ref, src, chain in (('U1', 'rsv_u1', ('JTAG_TDI', 'JTAG_LINK')), ('U2', 'rsv_u2', ('JTAG_LINK', 'JTAG_TDO'))):
    dev = cupl.Device((ROOT / 'cpld' / f'{src}.pld').read_text(encoding='utf-8'))
    DEV[ref] = dev
    tri = {t for t, e in dev.eq if e == 'oe'}

    def cpld_pin(p, dev=dev, tri=tri):
        if p in VCC_PINS: return (p, 'VCC', 'power_in')
        if p in GND_PINS: return (p, 'GND', 'power_in')
        if p in JTAG_PINS: return (p, JTAG_PINS[p], 'bidirectional')
        n = dev.pins.get(p)
        if n is None: return (p, f'NC{p}', 'no_connect')
        if n in dev.inputs: return (p, n, 'input')
        return (p, n, 'tri_state' if n in tri else 'output')

    key = d.custom(f'ATF1502AS_{src.upper()}', [cpld_pin(p) for p in range(1, 23)],
                   [cpld_pin(p) for p in range(44, 22, -1)], FP_PLCC, width=38.1)
    jtag = {'TDI': chain[0], 'TDO': chain[1], 'TMS': 'JTAG_TMS', 'TCK': 'JTAG_TCK'}
    cnets = {}
    for p in range(1, 45):
        if p in VCC_PINS: cnets[p] = '+5V'
        elif p in GND_PINS: cnets[p] = 'GND'
        elif p in JTAG_PINS: cnets[p] = jtag[JTAG_PINS[p]]
        elif p in dev.pins: cnets[p] = NET.get(dev.pins[p], dev.pins[p])
        else: cnets[p] = None
    d.add(ref, key, 'ATF1502AS-10JU44', cnets, (110, 60 + 200 * (ref == 'U2')))

# ---- J3: Atmel 10-pin ISP/JTAG header; the two devices sit in one chain ----------------------
k = d.standard('Connector_Generic', 'Conn_02x05_Odd_Even', FP_JTAG)
d.add('J3', k, 'JTAG', {1: 'JTAG_TCK', 2: 'GND', 3: 'JTAG_TDO', 4: '+5V', 5: 'JTAG_TMS',
                        6: None, 7: None, 8: None, 9: 'JTAG_TDI', 10: 'GND'}, (110, 450))

# ---- U3: 128K SRAM, 2 pages of 480 x 128 bytes. OE# grounded -- the CPLDs delay the 245 ----
k = d.standard('Memory_RAM', 'AS6C1008-xxP', DIP(32, 15.24))
m = {'GND': 'GND', 'VCC': '+5V', '~{CS1}/~{CE1}': 'GND', 'CS2/CE2': '+5V',
     '~{OE}': 'GND', '~{WE}': '~{SRAM_WE}', 'NC': None}
m.update({f'A{i}': f'MA{i}' for i in range(17)})
m.update({f'DQ{i}': f'MD{i}' for i in range(8)})
d.add('U3', k, 'AS6C1008-55PCN', named(k, m), (270, 90))

# ---- U4: data transceiver. A = SRAM side, B = CPU side; DIR = R/W (1 = read: SRAM -> CPU) ----
k = d.standard('74xx', '74HC245', DIP(20))
m = {'A->B': 'RWB', 'CE': '~{BUF_OE}', 'VCC': '+5V', 'GND': 'GND'}
m.update({f'A{i}': f'MD{i}' for i in range(8)})
m.update({f'B{i}': f'D{i}' for i in range(8)})
d.add('U4', k, '74HCT245', named(k, m), (270, 200))

# ---- U5: pixel serialiser. Loads a byte on /LOAD and shifts the MSB (leftmost pixel) out
#      first; while blanking U1 holds /LOAD high and the grounded serial input shifts black in.
#      It stays discrete because a CPLD has no pins left for MD0..MD7. Nexperia specify the
#      74HC166 at 40 MHz (4.5 V, full temperature range), so 25.000 MHz has plenty of margin;
#      its output only has to drive Q1's base, not the video lines.
k = d.standard('74xx', '74LS166', DIP(16))
m = {'Ds': 'GND', 'CE': 'GND', 'Clk': 'CLK25', 'Clr': '+5V', 'PE': '~{LOAD}', 'Qh': 'PIXEL',
     'VCC': '+5V', 'GND': 'GND'}
m.update({ch: f'MD{i}' for i, ch in enumerate('ABCDEFGH')})
d.add('U5', k, '74HC166', named(k, m), (340, 90))

# ---- X1: 25.000 MHz can into both CPLDs' GCLK1 and the 74HC166 shift clock ----
k = d.standard('Oscillator', 'CXO_DIP8', FP_OSC)
d.add('X1', k, '25.000MHz', {1: '+5V', 4: 'GND', 5: 'CLK25', 8: '+5V'}, (340, 200))

# ---- video output ---------------------------------------------------------------------------
# Three 75 ohm monitor inputs want 9.3 mA each at full white, about 26 mA from one driver. No
# 74HC/AC output is specified for that (74HC166: IOH 4 mA, 20 mA absolute maximum), so Q1 is an
# emitter follower: the shift register drives its base through R6 at a few hundred microamps and
# Q1 supplies the current. The level is then set by R1-R3 alone, so fitting only some of them
# changes the colour without changing the brightness.
R = d.standard('Device', 'R', FP_R)
d.add('R6', R, '220', {1: 'PIXEL', 2: 'Q_BASE'}, (410, 100))
k = d.standard('Transistor_BJT', 'Q_NPN_EBC', 'Package_TO_SOT_THT:TO-92_Inline')
d.add('Q1', k, '2N3904', {1: 'VIDEO', 2: 'Q_BASE', 3: '+5V'}, (440, 100))
for i, (ref, out) in enumerate([('R1', 'VGA_R'), ('R2', 'VGA_G'), ('R3', 'VGA_B')]):
    d.add(ref, R, '390', {1: 'VIDEO', 2: out}, (480, 40 + 30 * i))
d.add('R4', R, '47', {1: '~{HSYNC}', 2: 'VGA_HS'}, (440, 170))
d.add('R5', R, '47', {1: '~{VSYNC}', 2: 'VGA_VS'}, (470, 170))
k = d.standard('Connector', 'DE15_Socket_HighDensity_MountingHoles', FP_VGA)
vga = {1: 'VGA_R', 2: 'VGA_G', 3: 'VGA_B', 4: None, 5: 'GND', 6: 'GND', 7: 'GND', 8: 'GND', 9: None, 10: 'GND',
       11: None, 12: None, 13: 'VGA_HS', 14: 'VGA_VS', 15: None, 'SH': 'GND'}
d.add('J2', k, 'VGA', vga, (530, 100))

# ---- power ---------------------------------------------------------------------
C = d.standard('Device', 'C', FP_C)
CP = d.standard('Device', 'C_Polarized', FP_CP)
FLG = d.standard('power', 'PWR_FLAG', '')
for i in range(1, 9):          # C1..C5 bypass U1..U5, C6 X1, C7/C8 the CPLDs' second pair
    d.add(f'C{i}', C, '100nF', {1: '+5V', 2: 'GND'}, (380 + 15.24 * ((i - 1) % 8), 290))
d.add('C9', CP, '47uF 10V', {1: '+5V', 2: 'GND'}, (380, 350))
d.add('#FLG01', FLG, 'PWR_FLAG', {1: '+5V'}, (455, 345))
d.add('#FLG02', FLG, 'PWR_FLAG', {1: 'GND'}, (475, 345))

d.note(f'VRAM ${BASE:06X}-${BASE + 0xFFFFF:06X}: byte access (LDS) only, byte n of the SRAM at ${BASE + 1:06X} + 2n. '
       f'n = page << 16 | y << 7 | x >> 3 (x < 640, y < 480); bit 7 of the byte is the leftmost pixel.', 20, 385, 2)
d.note(f'${REG:06X} write: b0 video on, b1 page shown (reset: 0, screen black, page 0). '
       f'Read: b0 VBLANK, b1 HBLANK. The register repeats over $B00001-$BFFFFF.', 20, 391, 2)
d.note('U1 cpld/rsv_u1.pld, U2 cpld/rsv_u2.pld -- both ATF1502AS-10JU44 (CUPL; WinCUPL + fitter, one JTAG chain on J3). '
       'VGA 640x480 @ 60 Hz from 25.000 MHz: 100 bytes per line, HSYNC byte times 83-94, VSYNC lines 490-491.', 20, 397, 2)

d.write(ROOT, [('SolderDemonReallySimpleVideo', '${KIPRJMOD}/SolderDemonReallySimpleVideo.pretty')])
subprocess.run([sys.executable, str(Path(__file__).with_name('make_bus_footprint.py'))], check=True)

# ---- PCB -----------------------------------------------------------------------
b = pcb.BOARD()
b.SetCopperLayerCount(2)
v = lambda x, y: pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))
nets = {}
for i, n in enumerate(sorted(d.netlist()), 1):
    ni = pcb.NETINFO_ITEM(b, '/' + n, i)
    b.Add(ni)
    nets[n] = ni
fps = {}
for p in d.parts:
    if p['ref'].startswith('#'):
        continue
    lib, name = p['fp'].split(':')
    f = pcb.FootprintLoad(str(LOCAL_FP if lib == 'SolderDemonReallySimpleVideo' else g.LIB / 'footprints' / (lib + '.pretty')), name)
    assert f, p['fp']
    f.SetFPID(pcb.LIB_ID(lib, name))
    f.SetReference(p['ref'])
    f.SetValue(p['value'])
    f.SetPath(pcb.KIID_PATH('/' + d.uid('root') + '/' + p['uuid']))
    for pad in f.Pads():
        net = p['nets'].get(pad.GetNumber())
        if net:
            pad.SetNet(nets[net])
    f.Value().SetVisible(False)
    f.Reference().SetTextSize(v(1, 1))
    f.Reference().SetTextThickness(pcb.FromMM(.15))
    b.Add(f)
    fps[p['ref']] = f


def place(ref, x, y, rot=0, pin1=False):
    """pin1=True: (x, y) is pad 1; otherwise the footprint body is centred on (x, y)."""
    f = fps[ref]
    f.SetOrientationDegrees(rot)
    f.SetPosition(v(0, 0))
    if pin1:
        f.SetPosition(v(x, y))
        return f
    c = f.GetBoundingBox(False).GetCenter()
    f.SetPosition(pcb.VECTOR2I(pcb.FromMM(x) - c.x, pcb.FromMM(y) - c.y))
    return f


def ref_at(ref, x, y, angle=0):
    t = fps[ref].Reference()
    t.SetPosition(v(x, y))
    t.SetTextAngle(pcb.EDA_ANGLE(angle, pcb.DEGREES_T))


def dip(ref, left, y):
    """DIP lying horizontally, pin 1 towards the bus (right), left edge at `left`; cap to its right."""
    f = place(ref, left + 13, y, 270)
    f.Move(pcb.VECTOR2I(pcb.FromMM(left) - f.GetBoundingBox(False).GetLeft(), 0))
    right = pcb.ToMM(f.GetBoundingBox(False).GetRight())
    ref_at(ref, left - 1.3, y, 90)
    cref = f'C{ref[1:]}'
    place(cref, right + 2.2, y, 90)
    ref_at(cref, right + 2.2 + 2.8, y, 90)
    return right + 4.0


BX = W - 6.0
place('J1', BX, 87.37, 180, pin1=True)
ref_at('J1', BX + 1.27, 91.2)

# The two CPLDs sit against the bus connector, U1 (bus side) above U2 (address side).
place('U1', 66.0, 20.0, 0)
ref_at('U1', 66.0, 6.0)
place('U2', 66.0, 62.0, 0)
ref_at('U2', 66.0, 48.0)
place('C1', 51.0, 14.0, 90)
ref_at('C1', 48.2, 14.0, 90)
place('C7', 51.0, 26.0, 90)
ref_at('C7', 48.2, 26.0, 90)
place('C2', 51.0, 56.0, 90)
ref_at('C2', 48.2, 56.0, 90)
place('C8', 51.0, 68.0, 90)
ref_at('C8', 48.2, 68.0, 90)

# SRAM, transceiver and serialiser down the left side.
dip('U3', 3.0, 20.0)
dip('U4', 3.0, 44.0)
dip('U5', 3.0, 62.0)

place('X1', 41.0, 36.0, 0)
ref_at('X1', 41.0, 44.2)
place('C6', 49.5, 36.0, 90)
ref_at('C6', 52.3, 36.0, 90)
place('C9', 36.0, 54.0, 0)
ref_at('C9', 36.0, 49.4)
place('J3', 66.0, 41.0, 90)
ref_at('J3', 66.0, 35.0)

# VGA socket on the bottom edge with its five series resistors straight above its pins.
# Kept to the left so the bottom right corner is free for the SolderDemon logo.
RES_X0, RES_Y = 20.0, 79.0
for i, ref in enumerate(['R4', 'R5', 'R1', 'R2', 'R3']):
    x = RES_X0 + 3.4 * i
    place(ref, x, RES_Y, 90)
    ref_at(ref, x, RES_Y - 6.3, 90)
place('R6', 14.0, 79.0, 90)
ref_at('R6', 14.0, 72.7, 90)
place('Q1', 7.5, 79.0, 0)
ref_at('Q1', 7.5, 74.0)
J2_PIN1_X = 34.0
place('J2', J2_PIN1_X, H - 6.83, 0, pin1=True)
ref_at('J2', 9.0, 94.5)


def seg(a, z, layer=pcb.F_SilkS, line=.15):
    e = pcb.PCB_SHAPE(b)
    e.SetShape(pcb.SHAPE_T_SEGMENT)
    e.SetStart(v(*a))
    e.SetEnd(v(*z))
    e.SetLayer(layer)
    e.SetWidth(pcb.FromMM(line))
    b.Add(e)


def arc(start, mid, end):
    e = pcb.PCB_SHAPE(b)
    e.SetShape(pcb.SHAPE_T_ARC)
    e.SetArcGeometry(v(*start), v(*mid), v(*end))
    e.SetLayer(pcb.Edge_Cuts)
    e.SetWidth(pcb.FromMM(.05))
    b.Add(e)


def text(s, x, y, size=1.0, layer=pcb.F_SilkS, left=True, angle=0, bold=False):
    t = pcb.PCB_TEXT(b)
    t.SetText(s)
    t.SetPosition(v(x, y))
    t.SetTextSize(v(size, size))
    t.SetTextThickness(pcb.FromMM(size * (.2 if bold else .15)))
    t.SetLayer(layer)
    if left:
        t.SetHorizJustify(pcb.GR_TEXT_H_ALIGN_LEFT)
    if angle:
        t.SetTextAngle(pcb.EDA_ANGLE(angle, pcb.DEGREES_T))
    if layer == pcb.B_SilkS:
        t.SetMirrored(True)
    b.Add(t)


r = 3.0
k45 = r * (1 - 0.70710678)
seg((r, 0), (W - r, 0), pcb.Edge_Cuts, .05)
seg((W, r), (W, H - r), pcb.Edge_Cuts, .05)
seg((W - r, H), (r, H), pcb.Edge_Cuts, .05)
seg((0, H - r), (0, r), pcb.Edge_Cuts, .05)
arc((W - r, 0), (W - k45, k45), (W, r))
arc((W, H - r), (W - k45, H - k45), (W - r, H))
arc((r, H), (k45, H - k45), (0, H - r))
arc((0, r), (k45, k45), (r, 0))

# SolderDemon identity as on solderdemon_m68k-busboard and -gpio: the pixel logo with the name beside
# it, in the bottom right corner between the VGA socket and the bus connector.
LX0, LOGO_W, GAP, MID = 47.0, 13.2, 1.5, 85.5
logo = pcb.FootprintLoad(str(LOCAL_FP), 'SolderDemon_Logo'); logo.SetFPID(pcb.LIB_ID('SolderDemonReallySimpleVideo', 'SolderDemon_Logo'))
logo.SetReference('LOGO1'); logo.SetPosition(v(LX0 + LOGO_W / 2, MID)); b.Add(logo)
tx = LX0 + LOGO_W + GAP
text('SolderDemon', tx, MID - 1.6, 1.6, bold=True)
text('Really Simple Video', tx, MID + 1.4, 1.0)
text(f'{REV}   VGA 640x480 mono', tx, MID + 3.4, .8)
text('BUS', BX + 1.27, 5, 1.0, left=False)
# Back: chip notes between U5 and the resistors, register map and copyright behind the logo.
# Mirrored text is centred: left-justified mirrored text runs off to the left.
for i, line in enumerate(['R: b0 VBLANK b1 HBLANK   640x480, 2 pages',
                          'U1 bus  U2 line/address   ATF1502AS, JTAG on J3']):
    text(line, 24.0, 69.6 + i * 1.5, .8, pcb.B_SilkS, left=False)
for i, line in enumerate([f'REALLY SIMPLE VIDEO {REV}', f'VRAM ${BASE + 1:06X} + 2n', 'n = page<<16|y<<7|x>>3',
                          'bit 7 = leftmost pixel', f'${REG:06X} W: b0 on, b1 page',
                          NAME, f'{REV} (September 2026)', 'Copyright ©2026 SolderDemon']):
    text(line, 64.0, 82.3 + i * 1.5, .8, pcb.B_SilkS, left=False, bold=i == 0)

# No-connect pins get 'unconnected-(...)' nets in the schematic; copy nets and pin metadata onto the pads.
netlist = ROOT / 'netlist.xml'
subprocess.run([CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', str(netlist), str(ROOT / f'{NAME}.kicad_sch')], check=True, capture_output=True)
for n in ET.parse(netlist).findall('./nets/net'):
    for node in n.findall('node'):
        f = fps.get(node.get('ref'))
        pad = next((pd for pd in f.Pads() if pd.GetNumber() == node.get('pin')), None) if f else None
        if pad is None:
            continue
        ni = b.FindNet(n.get('name'))
        if ni is None:
            ni = pcb.NETINFO_ITEM(b, n.get('name'))
            b.Add(ni)
        pad.SetNet(ni)
        if node.get('pinfunction'):
            pad.SetPinFunction(node.get('pinfunction'))
        if node.get('pintype'):
            pad.SetPinType(node.get('pintype'))
netlist.unlink()

pcb.SaveBoard(str(ROOT / (NAME + '.kicad_pcb')), b)
pcb.ExportSpecctraDSN(b, str(ROOT / 'routing.dsn'))
print('Generated', len(d.parts), 'symbols;', len(nets), 'nets;', f'{W:g} x {H:g} mm')
