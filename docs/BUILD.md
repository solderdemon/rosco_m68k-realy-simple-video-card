# Regenerating this card

Nothing in this project is edited by hand except `tools/`, `cpld/`, `software/` and the
`.kicad_pro` file. The schematic, the symbol library, the footprints, the PCB, `design.json`,
`BOM.csv` and the manufacturing outputs are all generated, and the next run of the generator
overwrites them. Open KiCad to *look* at the result, not to change it.

The current board is already routed. Use `tools/regenerate_brand.py` for repeatable branding;
running `tools/build_card.py` directly replaces the PCB with an unrouted placement board.

`cpld/rsv_u1.pld` and `cpld/rsv_u2.pld` are the single source of truth for both the logic **and**
the CPLD pinouts: `build_card.py` reads the pin numbers out of them to build the schematic
symbols, and `sim_card.py` evaluates the equations to simulate the card. Move a signal to another
pin there and everything follows.

## Tools

| What | Where |
|---|---|
| KiCad 10 | `C:/Program Files/KiCad/10.0/bin/python.exe`, `kicad-cli.exe` |
| WinCUPL + the ATF150x fitter | Microchip, free — for the CPLD firmware |
| A JTAG programmer | USB Blaster clone with ATMISP or OpenOCD |
| Java | Temurin **25 or newer** — Freerouting 2.4.1 is built for class file 69 and will not start on 21 |
| Freerouting | `../tools/freerouting-2.4.1.jar`, found automatically |
| clang (or any C compiler) | only for the host driver test |

Anything that imports `pcbnew` has to run under KiCad's own Python, not the system one. **There is
no CPLD toolchain on the machine this card was designed on**, so no `.jed` is in the repo and the
fits have never been checked — see [BRINGUP §1](BRINGUP.md#1-compile-and-program-the-two-cplds).

## The pipeline

Each step is a gate: move on only when the current one is clean.

```sh
K="/c/Program Files/KiCad/10.0/bin"
N=solderdemon_m68k-realy-simple-video-card

# 1. CPLD firmware -- WinCUPL, both .pld files, by hand.
#    Do this first: if either does not fit, nothing else matters.

# 2. The 8x8 console font -> software/font8x8.c (only after editing the pictures in make_font.py)
python tools/make_font.py

# 3. Schematic, symbols, footprints, BOM and design.json, preserving routed copper
"$K/python.exe" tools/regenerate_brand.py

# 4. Logic simulation of the whole netlist, running the real CUPL equations (~15 min)
python tools/sim_card.py

# 5. The driver against a model of the card
make -C software host-test

# 6. Only for a changed electrical design: run build_card.py in place to
#    create an unrouted PCB, then use Freerouting and repair its pours.
# "$K/python.exe" tools/build_card.py
# "$K/python.exe" tools/route_card.py

# 7. The gates
"$K/kicad-cli.exe" sch erc -o erc.rpt $N.kicad_sch
"$K/kicad-cli.exe" pcb drc --schematic-parity --severity-error --severity-warning \
    -o drc.rpt $N.kicad_pcb
```

`regenerate_brand.py` runs the placement generator in a temporary directory, checks the
generated pin-to-net map, and copies the schematic and libraries back. It then applies the
silkscreen and project branding to the routed board without replacing its copper and exports
manufacturing files and preview images. For a new hardware revision that actually needs
rerouting, run `build_card.py` and then `route_card.py`.

## Manufacturing outputs

```sh
"$K/kicad-cli.exe" pcb export gerbers --layers F.Cu,B.Cu,F.Adhesive,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts,F.Fab,B.Fab -o manufacturing/ $N.kicad_pcb
"$K/kicad-cli.exe" pcb export drill   -o manufacturing/ $N.kicad_pcb
"$K/kicad-cli.exe" pcb export pos --format csv --units mm -o manufacturing/$N-pos.csv $N.kicad_pcb
"$K/kicad-cli.exe" sch export pdf -o manufacturing/$N-schematic.pdf $N.kicad_sch
```

## Where things are decided

| Question | File |
|---|---|
| What each CPLD does, and every one of its pin numbers | `cpld/rsv_u1.pld`, `cpld/rsv_u2.pld` |
| Which chips exist, how they are wired, where they sit | `tools/build_card.py` |
| The PLCC-44 power and JTAG pins (not expressible in CUPL) | `VCC_PINS` / `GND_PINS` / `JTAG_PINS` in `tools/build_card.py` |
| The JTAG chain order | the `chain` tuples in `build_card.py`'s CPLD loop |
| DRC rules, net classes, severities | `<project>.kicad_pro` (never written by a script) |
| Corner radius and routing options | `tools/route_card.py` |
| Font glyphs | `tools/make_font.py` |

`build_card.py` re-imports KiCad's own netlist at the end and copies the nets onto the pads, which
catches any disagreement between what the generator thought it built and what KiCad read.

## The CUPL simulator

`tools/cupl.py` reads the subset of CUPL this project uses — `PIN`/`PINNODE`/`FIELD`, the
operators `! & # $`, field equality and ranges, and the `.d .t .ck .ar .oe .io` extensions — and
turns the equations into a little synchronous model. It is not a compiler: it lets the netlist
simulation run the real source, so what is tested is what the fitter will see.

It came from the abandoned ATF1508 revision of `rosco_m68k-simple-video`; the `$` (XOR) operator
was added here, because CPLD-style counters need it to stay inside five product terms per
macrocell.

`sim_card.py` instantiates it twice — once per `.pld` — and wires the two models together through
the netlist exactly as the board does, so `SEL_N`, `LEND` and `VBLANK` are simulated as real nets
rather than assumed.

## Earlier revisions

Both are complete and archived under `rosco_m68k-realy-simple-video-card-backups/`; unzip either
over a clean directory.

- `r2-atf1502-single-2026-09-20.zip` — one ATF1502AS plus four 74HCT157, 8 ICs, one video page.
- `r1-gal-2026-09-20.zip` — four ATF22V10C plus four 74HCT157, 11 ICs. This is the only revision
  whose logic was verified from real JEDEC fuse maps, and the only one that programs on a TL866
  with no JTAG hardware at all.
