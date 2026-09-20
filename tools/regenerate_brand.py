"""Regenerate branded outputs while retaining the verified routed PCB.

Run with KiCad's Python from the project root. The placement generator is run in a
temporary project because it intentionally starts a PCB with no tracks.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'solderdemon_m68k-realy-simple-video-card'
OLD = 'rosco_m68k-realy-simple-video-card'
LIB = 'SolderDemonReallySimpleVideo'
BOARD = ROOT / f'{NAME}.kicad_pcb'
CLI = 'C:/Program Files/KiCad/10.0/bin/kicad-cli.exe'


def netmap(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    return {part['ref']: part['nets'] for part in data if 'nets' in part}


def brand_board():
    source = BOARD.read_text(encoding='utf-8')
    if '(segment ' not in source and '\n\t(segment' not in source:
        raise RuntimeError('The board has no routed segments; refusing the branding pass')
    result = source.replace('rosco_m68k Really Simple Video', 'SolderDemon m68k Really Simple Video')
    result = result.replace('RoscoReallySimpleVideo:', f'{LIB}:')
    result = result.replace(OLD, NAME)
    for token in ('(segment', '(via', '(zone'):
        if source.count(token) != result.count(token):
            raise RuntimeError(f'Copper item count changed: {token}')
    if result != source:
        BOARD.write_text(result, encoding='utf-8', newline='\n')


def export_artifacts():
    output = ROOT / 'manufacturing'
    output.mkdir(exist_ok=True)
    for command in (
        ('pcb', 'export', 'gerbers', '--layers',
         'F.Cu,B.Cu,F.Adhesive,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts,F.Fab,B.Fab',
         '-o', str(output), str(BOARD)),
        ('pcb', 'export', 'drill', '-o', str(output), str(BOARD)),
        ('pcb', 'export', 'pos', '--format', 'csv', '--units', 'mm', '-o', str(output / f'{NAME}-pos.csv'), str(BOARD)),
        ('sch', 'export', 'pdf', '-o', str(output / f'{NAME}-schematic.pdf'), str(ROOT / f'{NAME}.kicad_sch')),
    ):
        subprocess.run([CLI, *command], check=True)
    shutil.copy2(ROOT / 'BOM.csv', output / f'{NAME}-bom.csv')
    for label, options in (
        ('3d', ('--width', '1568', '--height', '872', '--rotate', '30,0,40', '--perspective')),
        ('top', ('--width', '1376', '--height', '872', '--side', 'top')),
        ('bottom', ('--width', '1376', '--height', '872', '--side', 'bottom')),
    ):
        subprocess.run([CLI, 'pcb', 'render', '-o', str(ROOT / f'{NAME}-{label}.png'),
                        *options, str(BOARD)], check=True, stdout=subprocess.DEVNULL)


def main():
    if not BOARD.is_file():
        raise RuntimeError(f'Missing routed board: {BOARD}')
    original_nets = netmap(ROOT / 'design.json')
    with tempfile.TemporaryDirectory(prefix='solderdemon-rsv-') as temporary:
        stage = Path(temporary)
        shutil.copytree(ROOT / 'tools', stage / 'tools', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'cpld', stage / 'cpld')
        shutil.copy2(ROOT / f'{NAME}.kicad_pro', stage / f'{NAME}.kicad_pro')
        subprocess.run([sys.executable, str(stage / 'tools' / 'build_card.py')], check=True)
        if netmap(stage / 'design.json') != original_nets:
            raise RuntimeError('Generated netlist differs from the routed revision')
        for filename in (f'{NAME}.kicad_sch', f'{LIB}.kicad_sym', 'fp-lib-table',
                         'sym-lib-table', 'BOM.csv', 'design.json'):
            shutil.copy2(stage / filename, ROOT / filename)
        for footprint in (stage / f'{LIB}.pretty').glob('*.kicad_mod'):
            shutil.copy2(footprint, ROOT / f'{LIB}.pretty' / footprint.name)
    brand_board()
    export_artifacts()
    print('Regenerated schematic, libraries, BOM, design.json, manufacturing outputs and images; retained routed copper')


if __name__ == '__main__':
    main()
