# Assembling and bringing up the card

No board has been manufactured yet — this is the procedure to follow with the first one, written
so that a fault stops you at the step that can still explain it.

Before anything else, read the fitter warning in the [README](../README.md#verification): U1 uses
32 of 32 pins and 29 of 32 macrocells, U2 30 and 23, and neither has been through WinCUPL.
**Compile both CPLD firmwares before you order the PCB.** If the fitter will not place a design on
the pins in its `.pld`, the board is wrong and there is no point having it made.

## 1. Compile and program the two CPLDs

You need Microchip's WinCUPL (free) with the ATF150x fitter, and a JTAG programmer — a USB Blaster
clone driven by ATMISP or OpenOCD is enough.

1. Open `cpld/rsv_u1.pld` in WinCUPL. The device (`f1502ispplcc44`) and the pin assignment are in
   the file, along with `PREASSIGN = KEEP`, which tells the fitter to honour them.
2. `Run → Device Dependent Compile`. Check `rsv_u1.fit`: every pin number must match the `.pld`,
   JTAG must be ON, and the macrocell count must be within 32.
3. Repeat for `cpld/rsv_u2.pld`.
4. Program both through J3. The devices are in one chain — TDI → U1 → U2 → TDO — so one run does
   both, but **`rsv_u1.jed` goes to U1 and `rsv_u2.jed` to U2**. Swapping them gives a board that
   looks alive and shows nothing.

If a fitter run fails, see [DESIGN §10](DESIGN.md#10-if-the-fitter-says-no). The first thing to try
is letting it choose the pins and then feeding its pinout back into the `.pld` and regenerating the
board. Never fix a pin conflict by editing the schematic.

The CPLDs can be programmed in their sockets on the finished board — J3 carries +5 V and ground,
so the card must be in a powered backplane while you do it.

## 2. Solder

Order: sockets, then resistors and capacitors, then J1, J2 and J3, then the oscillator.

- **Every IC goes in a socket.** 2 × PLCC-44 through-hole sockets, 1 × DIP-32 (600 mil),
  1 × DIP-20, 1 × DIP-16, 1 × DIP-8 for the oscillator. Note each PLCC socket's pin 1 corner —
  the chamfered corner on the silkscreen.
- **U5 is an ordinary 74HC166.** It only drives Q1's base, so no fast or high-current family is
  needed; check that the part you buy is rated past 25 MHz (Nexperia's is 40 MHz at 4.5 V).
- **Q1 is a small-signal NPN in TO-92** — 2N3904, BC547, BC337, 2N2222 all work. Watch the
  orientation: the footprint is the JEDEC E-B-C inline order, flat side as drawn on the silkscreen.
- **X1 is a canned oscillator**, not a crystal. 25.000 MHz.
- R1, R2 and R3 are 390 Ω (video), R4 and R5 are 47 Ω (sync), R6 is 220 Ω (Q1's base). R1–R5 stand
  in one row above J2, left to right R4 R5 R1 R2 R3 = HSYNC, VSYNC, red, green, blue. Fitting only
  R2 gives a green screen, only R1 + R2 an amber one, both at the same brightness.
- C9 is polarised: the long leg goes to +5 V.

Before putting any IC in its socket, power the card from the bus and check +5 V and 0 V on every
socket's supply pins — including all four VCC/GND pairs of each PLCC socket (3, 15, 23, 35 and
10, 22, 30, 42).

## 3. First power-up: the raster alone

Fit **only X1, U1 and U2**. Leave the SRAM, the transceiver and the serialiser out.

Plug a monitor into J2. The screen will be black, but it should **lock**: the OSD should report
640 × 480 at 60 Hz rather than "no signal" or "out of range".

| Symptom | Look at |
|---|---|
| No signal at all | X1 pin 5: 25.000 MHz. Then pin 43 of both CPLDs — the same signal |
| HSYNC but no VSYNC, or VSYNC at the wrong rate | `LEND`, U1 pin 34 → U2 pin 44: a 31.25 kHz pulse one clock wide. This is the wire that makes U2's line counter run |
| Out of range, or the picture rolls | U1 pin 41 (/HSYNC): 31.25 kHz, 3.84 µs low. U2 pin 40 (/VSYNC): 59.52 Hz |
| Locks at the wrong rate | the wrong `.jed` in one of the sockets, or the two swapped |

With just these two chips you can also watch the low address half on U1 pins 4–12 (MA0–MA6) and
the high half on U2 pins 4–16 (MA7–MA15): MA0 should be a clean 3.15 MHz, MA7 a clean 15.7 kHz.

## 4. The rest of the card

Power down, fit U3, U4 and U5, and power up again. The screen should still be black — `/RESET`
clears `VIDEOON`, so the card comes up blanked on purpose.

Now load the demo (`software/`, see [BUILD.md](BUILD.md)) over the serial bootloader. It runs the
VRAM self test first and prints the result to the serial console:

```
Really Simple Video: testing 2 x 60K of VRAM...
VRAM ok. 640x480 should now be on the VGA output.
```

`video_selftest()` writes both pages completely before reading either back, so a stuck or shorted
address line — including the page bit, which lives in the *other* CPLD — shows up as one page
overwriting the other rather than as a picture that is subtly wrong.

| Symptom | Likely cause |
|---|---|
| Bus error on the first VRAM write | `/DTACK` — U1 pin 28 to J1 pin 57 |
| Self test fails at byte 0 of page 1 only | MA16 — U2 pin 17 to U3 pin 2 |
| Self test fails on a regular pattern within a row | an MA0–MA6 line (U1) |
| Self test fails on a regular pattern of rows | an MA7–MA15 line (U2) |
| Self test passes, screen stays black | `VIDEOON` never got set (U1 pin 29 = D0 to J1 pin 61), or `/LOAD` (U1 pin 40 → U5 pin 15) |
| A picture, but every eighth pixel column wrong | U5 data pins: A = MD0 … H = MD7 |
| The picture is mirrored inside each byte | same — A and H swapped |
| Picture shifted sideways by one byte | U1's HBLANK decode; it should stop the load at byte 79 |
| Page flipping does nothing | U2's page register: D1 (U2 pin 34), A20 (pin 31), R/W (pin 33), SEL_N (pin 36) |
| Garbage on the data bus during writes | the BUFD delay — see [DESIGN §6](DESIGN.md#sram-oe-and-bufd) |

## 5. Things worth a scope

- **`LEND`, U1 pin 34.** This is the only timing hand-off between the two chips. It is a register
  in U1 and must be high for exactly one 25 MHz clock, once per line, at the end of the HSYNC
  pulse.
- **MD during a VRAM write.** `WE#` (U3 pin 29) falls with `/LDS`; `/BUF_OE` (U1 pin 39) must fall
  one 25 MHz clock later, about 40 ns. If they move together, the SRAM and the 74HCT245 briefly
  fight over MD. This is the one place the design trades a pin for a timing assumption.
- **The address halves.** MA0–MA6 comes from U1 and MA7–MA16 from U2, so they settle a few
  nanoseconds apart when the CPU takes the bus. That is harmless — `WE#` arrives much later — but
  it is worth seeing once.
- **The video level.** Q1's emitter should sit at about 4.1 V while a white pixel is on, and each
  of J2 pins 1-3 at about 0.67 V into a connected monitor. If the picture is dim, check Q1's
  orientation before anything else.
- **Snow.** Writing to VRAM while the picture is on will flicker eight pixels on the current line.
  That is expected; draw on the hidden page and `video_flip()`.

## 6. Still to be verified on real hardware

- **that both halves fit an ATF1502AS at all** — see step 1;
- real propagation delays, inside the CPLDs and on the board;
- the BUFD timing and the LEND hand-off above;
- the 0.67 V video level on a real monitor, and monitor tolerance of the timing;
- a build with the SolderDemon m68k toolchain;
- the board itself — no PCB has been ordered.
