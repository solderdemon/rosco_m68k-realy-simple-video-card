# Regenerating this card

Nothing in this project is edited by hand except `tools/`, `cpld/`, `software/` and the
`.kicad_pro` file. The schematic, the symbol library, the footprints, the PCB, `design.json`,
`BOM.csv` and the manufacturing outputs are all generated, and the next run of the generator
overwrites them. Open KiCad to *look* at the result, not to change it.

`tools/build_card.py` always writes a PCB **without tracks**, so any change to the schematic,
placement or silkscreen means re-routing with `tools/route_card.py`.

`cpld/rsv_u1.pld` and `cpld/rsv_u2.pld` are the single source of truth for both the logic **and**
the CPLD pinouts: `build_card.py` reads the pin numbers out of them to build the schematic
symbols, and `sim_card.py` evaluates the equations to simulate the card. Move a signal to another
pin there and everything follows.

## Tools

| What | Where |
|---|---|
| KiCad 10 | `C:/Program Files/KiCad/10.0/bin/python.exe`, `kicad-cli.exe` |
| WinCUPL + the ATF150x fitter | Docker image `dinoboards/cpld-toolchain` (see `../tools/cpld-toolchain`), Docker Desktop running |
| A JTAG programmer | USB Blaster clone with ATMISP or OpenOCD |
| Java | Temurin **25 or newer** — Freerouting 2.4.1 is built for class file 69 and will not start on 21 |
| Freerouting | `../tools/freerouting-2.4.1.jar`, found automatically |
| clang (or any C compiler) | only for the host driver test |

Anything that imports `pcbnew` has to run under KiCad's own Python, not the system one. The CPLD
firmware is built in Docker; `cpld/bin/` keeps the `.jed` and `.fit` of the last build.

## The pipeline

Each step is a gate: move on only when the current one is clean.

```sh
K="/c/Program Files/KiCad/10.0/bin"
N=solderdemon_m68k-realy-simple-video-card

# 1. CPLD firmware: WinCUPL + fitter in docker -> cpld/bin/*.jed, pin check, and
#    tools/check_fit.py (fitted equations == the cupl.py model the simulation runs).
#    Do this first: if either does not fit, nothing else matters.
./cpld/build.sh

# 2. The 8x8 console font -> software/font8x8.c (only after editing the pictures in make_font.py)
python tools/make_font.py

# 3. Schematic, symbols, footprints, BOM, design.json and the unrouted, placed PCB
"$K/python.exe" tools/build_card.py

# 4. Logic simulation of the whole netlist, running the real CUPL equations (~15 min)
python tools/sim_card.py

# 5. The driver against a model of the card
make -C software host-test

# 6. Freerouting swarm, GND pours, cleanup (ROUTE_MODE=best for a release)
ROUTE_MODE=best "$K/python.exe" tools/route_card.py

# 7. The gates
"$K/kicad-cli.exe" sch erc -o erc.rpt $N.kicad_sch
"$K/kicad-cli.exe" pcb drc --schematic-parity --severity-error --severity-warning \
    -o drc.rpt $N.kicad_pcb
```

The SolderDemon logo footprint is generated from `logo.png` (the same image as on
`solderdemon_m68k-busboard` and `solderdemon_m68k-gpio`) by `python tools/make_logo.py`; it only
needs re-running when the image or its size (14 mm tall) changes.

## Manufacturing outputs

```sh
"$K/kicad-cli.exe" pcb export gerbers --layers F.Cu,B.Cu,F.Adhesive,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts,F.Fab,B.Fab -o manufacturing/ $N.kicad_pcb
"$K/kicad-cli.exe" pcb export drill   -o manufacturing/ $N.kicad_pcb
"$K/kicad-cli.exe" pcb export pos --format csv --units mm -o manufacturing/$N-pos.csv $N.kicad_pcb
"$K/kicad-cli.exe" sch export pdf -o manufacturing/$N-schematic.pdf $N.kicad_sch

# Preview images. The 3D view is lit by the camera light only: any top or side light leaves a
# specular glare on the solder mask. --pan recentres the board, whose connectors stick out
# to the right and bottom.
"$K/kicad-cli.exe" pcb render --side top --width 1600 --height 1000 -o $N-top.png $N.kicad_pcb
"$K/kicad-cli.exe" pcb render --side bottom --width 1600 --height 1000 -o $N-bottom.png $N.kicad_pcb
"$K/kicad-cli.exe" pcb render --side top --perspective --rotate -40,0,-20 --zoom 0.8 --pan " 0.6,1.4,0"     --background transparent --light-camera 1 --light-top 0 --light-side 0 --light-bottom 0     --width 1600 --height 1000 -o $N-3d.png $N.kicad_pcb
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

The `$` (XOR) operator is supported because CPLD-style counters need it to stay inside five
product terms per macrocell.

`sim_card.py` instantiates it twice — once per `.pld` — and wires the two models together through
the netlist exactly as the board does, so `SEL_N`, `LEND` and `VBLANK` are simulated as real nets
rather than assumed.
