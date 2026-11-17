"""Check that what WinCUPL actually fitted behaves exactly like tools/cupl.py's model of the .pld.

sim_card.py proves the card with tools/cupl.py's reading of the CUPL source. That reading can
differ from the compiler's -- it did for `!FIELD:[lo..hi]`, which CUPL takes as "the complemented
field is in range" -- so this script closes the loop: it parses the sum-of-products equations the
ATF1502AS fitter wrote into code/firmware/cpld/bin/<name>.fit and compares them with the model on random input
pins and random register states (every output, its enable, every next state, the async clear).

    python tools/check_fit.py rsv_u1 rsv_u2        (after code/firmware/cpld/build.sh)
"""
from pathlib import Path
import random, re, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
import cupl

VECTORS = 200000


def fitted(text):
    """{(signal, EXT): (negated, sum-of-products)} from the fitter's 'programmed logic' section."""
    sec = text.split('programmed logic:')[1].split('Pin/Node Placement')[0]
    eqs = {}
    for st in (s.strip() for s in sec.split(';')):
        st = re.sub(r'-{5,}', '', st).strip()
        if '=' not in st:
            continue
        lhs, rhs = (x.strip() for x in st.split('=', 1))
        name, _, ext = lhs.lstrip('!').partition('.')
        eqs[(name, ext.upper())] = (lhs.startswith('!'), rhs)
    return eqs


def check(name):
    dev = cupl.Device((ROOT / 'code' / 'firmware' / 'cpld' / f'{name}.pld').read_text(encoding='utf-8'))
    eqs = fitted((ROOT / 'code' / 'firmware' / 'cpld' / 'bin' / f'{name}.fit').read_text(encoding='latin-1'))

    # The fitter may put a buried register straight into the macrocell of the pin that only
    # copies it (U1: `D1 = HBLANK` becomes register D1): give it back the model's name.
    for r in sorted({n for n, e in eqs if e in ('D', 'T')} - set(dev.regs)):
        m = dev.eq.get((r, ''), '').strip()
        assert m in dev.regs, f'{name}: fitted register {r} is not in the model'
        eqs = {k: (neg, re.sub(rf'\b{r}\.Q\b', f'{m}.Q', rhs)) for k, (neg, rhs) in eqs.items()}
        for e in ('D', 'T', 'C', 'AR'):
            if (r, e) in eqs:
                eqs[(m, e)] = eqs.pop((r, e))
        eqs[(r, '')] = (False, f'{m}.Q')

    regs = sorted({n for n, e in eqs if e in ('D', 'T')})
    combs = [n for n, e in eqs if e == '']
    assert set(regs) == set(dev.regs), (name, set(regs) ^ set(dev.regs))
    clock_of = getattr(dev, 'clock_of', None) or {r: dev.clock for r in regs}
    for r in regs:
        got = re.sub(r'\s+', '', eqs.get((r, 'C'), (0, ''))[1])
        assert got == re.sub(r'\s+', '', clock_of[r]), f'{name}: {r} clocked by {got}, not {clock_of[r]}'

    def operand(m):
        n = m.group(1)
        return n if n in ('0', '1') else f"c['{n}']" if n in combs else f"p['{n}']"

    def compile_(neg, rhs):
        e = re.sub(r'\b(\w+)\.Q\b', r"q['\1']", rhs)
        e = re.sub(r'\b(\w+)\.PIN\b', r"p['\1']", e)
        e = re.sub(r"(?<![\w'])(\w+)(?![\w'\[])", operand, e)
        e = e.replace('!', ' 1 - ').replace('&', ' and ').replace('#', ' or ')
        return eval(f"lambda p, q, c: int({'not ' if neg else ''}bool({e}))")

    F = {k: compile_(*v) for k, v in eqs.items() if k[1] != 'C'}

    def comb(p, q):
        c, todo = {}, list(combs)
        while todo:                      # fold-back nodes feed each other; settle in any order
            left = []
            for n in todo:
                try:
                    c[n] = F[(n, '')](p, q, c)
                except KeyError:
                    left.append(n)
            assert len(left) < len(todo), f'{name}: cannot evaluate {left}'
            todo = left
        return c

    outs = [n for n in dev.pins.values() if n not in dev.inputs]
    pins = sorted(set(dev.inputs) | set(outs))           # outputs can be read back as .PIN
    rnd, bad = random.Random(1), {}
    for _ in range(VECTORS):
        p = {n: rnd.getrandbits(1) for n in pins}
        q = {r: rnd.getrandbits(1) for r in regs}
        ar = {r: F[(r, 'AR')](p, q, comb(p, q)) if (r, 'AR') in F else 0 for r in regs}
        qa = {r: 0 if ar[r] else q[r] for r in regs}
        c = comb(p, qa)
        model = dev.outputs(p, dict(q))
        for n in outs:
            en = F[(n, 'OE')](p, qa, c) if (n, 'OE') in F else 1
            got = (qa[n] if n in regs else c[n]) if en else None
            if got != model[n]:
                bad[n] = bad.get(n, 0) + 1
        model = dev.clock_edge(p, dict(q))
        c = comb(p, q)
        for r in regs:
            nxt = F[(r, 'D')](p, q, c) if (r, 'D') in F else q[r] ^ F[(r, 'T')](p, q, c)
            if (0 if ar[r] else nxt) != model[r]:
                bad[r + '.D'] = bad.get(r + '.D', 0) + 1
    print(f'{name}: {len(regs)} registers, {len(outs)} outputs, {VECTORS} random vectors --',
          f'MISMATCH {bad}' if bad else 'fitted equations match the model')
    return not bad


if __name__ == '__main__':
    ok = [check(n) for n in sys.argv[1:] or sorted(f.stem for f in (ROOT / 'code' / 'firmware' / 'cpld').glob('*.pld'))]
    sys.exit(0 if all(ok) else 1)
