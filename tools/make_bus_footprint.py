"""Write the two edge connectors into SolderDemonReallySimpleVideo.pretty with the silkscreen that would lie on or
beyond the card edge removed: J1, the stock right-angle 2x32 socket, and J2, the stock DE-15 HD socket.

Runs as its own process: removing footprint items breaks pcbnew's SWIG type table for the
rest of the interpreter, so build_card.py must not do this in-process.
"""
from pathlib import Path
import pcbnew as pcb

ROOT = Path(__file__).resolve().parents[1]
STOCK = Path('/usr/share/kicad/footprints') if Path('/usr/share/kicad/footprints').exists() else Path('C:/Program Files/KiCad/10.0/share/kicad/footprints')
LIB = ROOT / 'design' / 'SolderDemonReallySimpleVideo.pretty'
NAME = 'PinSocket_2x32_P2.54mm_Horizontal_CardEdge'
EDGE_LOCAL_X = -5.5   # J1 is placed rotated 180 deg with pin 1 6 mm from the right edge

io = pcb.PCB_IO_MGR.FindPlugin(pcb.PCB_IO_MGR.KICAD_SEXP)
fp = io.FootprintLoad(str(STOCK / 'Connector_PinSocket_2.54mm.pretty'), 'PinSocket_2x32_P2.54mm_Horizontal')
fp.SetFPID(pcb.LIB_ID('SolderDemonReallySimpleVideo', NAME))
fp.SetLibDescription('2x32 2.54 mm right-angle socket for SolderDemon m68k (rosco_m68k compatible) cards; silkscreen stops at the card edge')
doomed = [item for item in fp.GraphicalItems()
          if item.GetLayer() == pcb.F_SilkS and pcb.ToMM(item.GetBoundingBox().GetLeft()) < EDGE_LOCAL_X]
LIB.mkdir(exist_ok=True)
for item in doomed:
    fp.Remove(item)
io.FootprintSave(str(LIB), fp)
print(f'{NAME}: removed {len(doomed)} silkscreen items')

VGA = 'DSUB-15-HD_Socket_Horizontal_P2.29x1.90mm_EdgePinOffset3.03mm_Housed_MountingHolesOffset4.94mm'
EDGE_LOCAL_Y = 6.0    # J2 is placed unrotated with pin 1 6.83 mm above the bottom edge
fp = io.FootprintLoad(str(STOCK / 'Connector_Dsub.pretty'), VGA)
fp.SetFPID(pcb.LIB_ID('SolderDemonReallySimpleVideo', VGA))
doomed = [item for item in fp.GraphicalItems()
          if item.GetLayer() == pcb.F_SilkS and pcb.ToMM(item.GetBoundingBox().GetBottom()) > EDGE_LOCAL_Y]
for item in doomed:
    fp.Remove(item)
io.FootprintSave(str(LIB), fp)
print(f'DSUB-15-HD: removed {len(doomed)} silkscreen items')
