# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Colour bar (legend) settings and label maths. Pure Python + numpy, no Qt."""
import math

import numpy as np

from . import stretch

DEFAULTS = dict(orientation='vertical', length=500, thickness=30, ticks=6, tick_mode='colour',
                decimals=-1, font_px=14, units='', background='transparent', fmt='png', scale=2)


def normalise(s):
    s = {**DEFAULTS, **(s or {})}
    if s['orientation'] not in ('vertical', 'horizontal'):
        s['orientation'] = 'vertical'
    if s['tick_mode'] not in ('colour', 'value'):
        s['tick_mode'] = 'colour'
    if s['background'] not in ('transparent', 'white'):
        s['background'] = 'transparent'
    if s['fmt'] not in ('png', 'svg', 'pdf'):
        s['fmt'] = 'png'
    s['length'] = int(min(4000, max(100, s['length'])))
    s['thickness'] = int(min(400, max(5, s['thickness'])))
    s['ticks'] = int(min(30, max(2, s['ticks'])))
    s['decimals'] = int(min(8, max(-1, s['decimals'])))
    s['font_px'] = int(min(72, max(6, s['font_px'])))
    s['scale'] = int(min(6, max(1, s['scale'])))
    return s


# ------------------------------------------------------------- tick maths
def nice_ticks(lo, hi, n):
    """Round-number ticks inside lo..hi, about n of them."""
    span = hi - lo
    if not span > 0:
        return [lo]

    def make(step):
        k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
        return [0.0 if k == 0 else k * step for k in range(k0, k1 + 1)]

    mag = 10 ** math.floor(math.log10(span / max(1, n - 1)))
    best = None
    for e in (mag / 10, mag, mag * 10):
        for m in (1, 2, 2.5, 5):
            vals = make(m * e)
            if len(vals) < 2:
                continue
            score = (abs(len(vals) - n), len(vals) > n)   # closest to n, prefer fewer when tied
            if best is None or score < best[0]:
                best = (score, vals)
    return best[1] if best else [lo, hi]


def bar_ticks(nodes, n, mode='colour'):
    """Where the colour bar starts/ends on the ramp and where its labels go.

    Returns dict(tmin, tmax, ticks=[(position 0..1 along the bar, data value)], mode).
    'colour': labels evenly spaced along the bar (values read back through the curve) —
              best for histogram-equalised stretches.
    'value' : round-number values, placed where the curve puts them.
    A curve that goes up and down can't be read backwards, so it always uses 'value'."""
    xs = np.array([p[0] for p in nodes], float)
    ys = np.array([p[1] for p in nodes], float)
    tmin, tmax = float(ys.min()), float(ys.max())
    if not tmax > tmin:
        tmax = tmin + 1e-9
    d = np.diff(ys)
    increasing, decreasing = bool(np.all(d >= 0)), bool(np.all(d <= 0))
    if mode == 'colour' and not (increasing or decreasing):
        mode = 'value'

    ticks = []
    if mode == 'colour':
        order = np.argsort(ys, kind='stable') if decreasing and not increasing else np.arange(len(ys))
        ys_s, xs_s = ys[order], xs[order]
        for t in np.linspace(tmin, tmax, n):
            v = float(np.interp(t, ys_s, xs_s))
            ticks.append(((t - tmin) / (tmax - tmin), v))
    else:
        for v in nice_ticks(xs[0], xs[-1], n):
            t = float(stretch.evaluate(nodes, [v])[0])
            ticks.append(((t - tmin) / (tmax - tmin), v))
    return dict(tmin=tmin, tmax=tmax, ticks=ticks, mode=mode)


def label_decimals(ticks, decimals=-1):
    if decimals >= 0:
        return decimals
    vals = [v for _, v in ticks]
    if len(vals) < 2:
        return 2
    gaps = np.abs(np.diff(sorted(vals)))
    gaps = gaps[gaps > 0]
    step = float(np.min(gaps)) if gaps.size else abs(vals[0]) or 1.0
    return int(min(6, max(0, -math.floor(math.log10(step)) + 1)))


def format_value(v, dec):
    s = f'{v:.{dec}f}'
    return '0' if s.strip('-0.') == '' else s


def labels(ticks, decimals=-1):
    """Formatted label strings for bar_ticks()['ticks']."""
    dec = label_decimals(ticks, decimals)
    return [format_value(v, dec) for _, v in ticks]
