# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Pure-numpy stretch maths (no QGIS dependency, so it can be unit tested).

A stretch is a list of nodes [[data_value, output], ...] with data values
strictly increasing and output in 0..1. Values outside the first/last node
are held flat (like ER Mapper's transform limits).
"""
import numpy as np


def _safe_range(lo, hi):
    lo, hi = float(lo), float(hi)
    if hi < lo:
        lo, hi = hi, lo
    if not hi > lo:
        hi = lo + max(abs(lo) * 1e-6, 1e-9)
    return lo, hi


def percent_clip(sample, lower_pct=0.0, upper_pct=100.0):
    """Data values at the lower and upper percentiles (0 and 100 = min and max)."""
    lower_pct, upper_pct = sorted((float(lower_pct), float(upper_pct)))
    lo, hi = np.percentile(sample, [lower_pct, upper_pct])
    if not hi > lo:
        lo, hi = np.min(sample), np.max(sample)
    return _safe_range(lo, hi)


def data_range(sample):
    return _safe_range(np.min(sample), np.max(sample))


def sanitize(nodes):
    """Sort, clamp outputs to 0..1 and force strictly increasing values."""
    nodes = sorted([[float(x), min(1.0, max(0.0, float(y)))] for x, y in nodes])
    out = []
    for x, y in nodes:
        if out and x <= out[-1][0]:
            x = out[-1][0] + max(abs(out[-1][0]) * 1e-9, 1e-12)
        out.append([x, y])
    return out


# ------------------------------------------------------------- presets
def preset_linear(sample, lo, hi, n=2):
    lo, hi = _safe_range(lo, hi)
    n = max(2, int(n))
    return sanitize(np.column_stack([np.linspace(lo, hi, n), np.linspace(0, 1, n)]).tolist())


def preset_histeq(sample, lo, hi, n=33):
    """Equal-area stretch: nodes placed at quantiles of the data inside lo..hi."""
    lo, hi = _safe_range(lo, hi)
    n = max(2, int(n))
    s = sample[(sample >= lo) & (sample <= hi)]
    if s.size < 2:
        return preset_linear(sample, lo, hi, n)
    q = np.linspace(0.0, 1.0, n)
    xs = np.quantile(s, q)
    xs[0], xs[-1] = lo, hi
    keep = np.concatenate([[True], np.diff(xs) > 0])
    xs, ys = xs[keep], q[keep]
    if xs.size < 2:
        return preset_linear(sample, lo, hi, n)
    ys = (ys - ys[0]) / (ys[-1] - ys[0])
    return sanitize(np.column_stack([xs, ys]).tolist())


def preset_log(sample, lo, hi, n=25, k=100.0):
    """Log-linear stretch: expands the low end of lo..hi."""
    lo, hi = _safe_range(lo, hi)
    n = max(2, int(n))
    xs = np.linspace(lo, hi, n)
    ys = np.log1p(k * (xs - lo) / (hi - lo)) / np.log1p(k)
    return sanitize(np.column_stack([xs, ys]).tolist())


PRESETS = {'linear': preset_linear, 'histeq': preset_histeq, 'log': preset_log}


# ------------------------------------------------------------- mirror about a centre value
def mirror_radius(sample, c, upper_pct=100.0):
    """Half-width R of a symmetric clip: the upper percentile of |x - c|."""
    d = np.abs(np.asarray(sample, float) - c)
    r = float(np.percentile(d, min(100.0, max(0.0, upper_pct))))
    if not r > 0:
        r = float(np.max(d)) or 1.0
    return r


def symmetric_preset(kind, sample, c, r, n=33):
    """Preset built on distance from c, mirrored: c -> 0.5 output, c+r -> 1, c-r -> 0."""
    half = max(2, (int(n) + 2) // 2)                    # rounds the total up to an odd count
    dist = np.abs(np.asarray(sample, float) - c)
    pos = PRESETS[kind](dist, 0.0, r, half)           # nodes on 0..r, outputs 0..1
    nodes = [[c + d, 0.5 + 0.5 * y] for d, y in pos if d > 0]
    return mirror(nodes + [[c, 0.5]], c, 'pos')


def mirror(nodes, c, side='pos'):
    """Make a curve symmetric about c from one side ('pos' = values above c).
    The centre is pinned at output 0.5. Returns None if that side has no nodes."""
    if side == 'neg':
        src = [[2 * c - x, 1.0 - y] for x, y in nodes if x < c]
    else:
        src = [[x, y] for x, y in nodes if x > c]
    if not src:
        return None
    src = sorted(src)
    neg = [[2 * c - x, 1.0 - y] for x, y in reversed(src)]
    return sanitize(neg + [[c, 0.5]] + src)


def reslope(nodes, factor):
    """Change the contrast around the middle of the ramp (output 0.5).
    Each output moves to 0.5 ± 0.5·|2(y − 0.5)|**factor; factor < 1 steepens the curve near
    the centre (more contrast for small values), factor > 1 flattens it. Ends stay put."""
    out = []
    for x, y in nodes:
        d = 2.0 * (y - 0.5)
        out.append([x, 0.5 + 0.5 * np.sign(d) * abs(d) ** factor])
    return sanitize(out)


def is_symmetric(nodes, c, tol=1e-9):
    xs = np.array([p[0] for p in nodes])
    ys = np.array([p[1] for p in nodes])
    return np.allclose(xs + xs[::-1], 2 * c, atol=tol * max(1.0, abs(c), np.ptp(xs))) and \
        np.allclose(ys + ys[::-1], 1.0, atol=1e-9)


# ------------------------------------------------------------- curve ops
def evaluate(nodes, values):
    xs = np.array([n[0] for n in nodes], dtype=float)
    ys = np.array([n[1] for n in nodes], dtype=float)
    return np.clip(np.interp(values, xs, ys), 0.0, 1.0)


def resample(nodes, n):
    """Change an edited curve to n nodes while keeping its shape.
    More nodes: split the longest segments (shape is unchanged).
    Fewer nodes: drop the least significant node each time (Visvalingam), so bends survive."""
    n = max(2, int(n))
    pts = [list(p) for p in sanitize(nodes)]
    x0, x1 = pts[0][0], pts[-1][0]

    def norm(p):
        return ((p[0] - x0) / (x1 - x0), p[1])

    while len(pts) < n:
        lens = [np.hypot(*np.subtract(norm(pts[i + 1]), norm(pts[i]))) for i in range(len(pts) - 1)]
        i = int(np.argmax(lens))
        pts.insert(i + 1, [(pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2])

    while len(pts) > n:
        best, area = 1, None
        for i in range(1, len(pts) - 1):
            (ax, ay), (bx, by), (cx, cy) = norm(pts[i - 1]), norm(pts[i]), norm(pts[i + 1])
            a = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))
            if area is None or a < area:
                best, area = i, a
        del pts[best]
    return sanitize(pts)


def rescale(nodes, lo, hi):
    """Linearly move node values so the curve spans lo..hi (keeps its shape)."""
    lo, hi = _safe_range(lo, hi)
    x0, x1 = nodes[0][0], nodes[-1][0]
    f = (hi - lo) / (x1 - x0)
    return sanitize([[lo + (x - x0) * f, y] for x, y in nodes])


class LinearAxis:
    log = False

    def fwd(self, v):
        return np.asarray(v, dtype=float)

    def inv(self, t):
        return np.asarray(t, dtype=float)

    def clamp(self, lo, hi):
        return lo, hi


class LogAxis:
    """Log x-axis for display. All-positive data uses log10; data with zero or negative
    values uses a symmetric log (linear near zero, log beyond +/- c)."""
    log = True

    def __init__(self, sample):
        s = np.asarray(sample, dtype=float)
        self.positive = bool(np.min(s) > 0)
        if self.positive:
            self.tiny = float(np.min(s)) * 1e-3
        else:
            a = np.abs(s[s != 0])
            self.c = float(np.percentile(a, 25)) if a.size else 1.0
            if not self.c > 0:
                self.c = 1.0

    def fwd(self, v):
        v = np.asarray(v, dtype=float)
        if self.positive:
            return np.log10(np.maximum(v, self.tiny))
        return np.sign(v) * np.log10(1.0 + np.abs(v) / self.c)

    def inv(self, t):
        t = np.asarray(t, dtype=float)
        if self.positive:
            return np.power(10.0, t)
        return np.sign(t) * self.c * (np.power(10.0, np.abs(t)) - 1.0)

    def clamp(self, lo, hi):
        if self.positive:
            lo = max(lo, self.tiny)
            hi = max(hi, lo * 1.0001)
        return lo, hi


def histogram(sample, lo, hi, bins=256):
    return np.histogram(sample, bins=bins, range=(lo, hi))


def fit_curve_view(nodes, pad=0.0):
    """View range from the first to the last node (optionally with a margin)."""
    lo, hi = _safe_range(nodes[0][0], nodes[-1][0])
    m = (hi - lo) * pad
    return lo - m, hi + m


# ------------------------------------------------------------- rendering
def apply_lut(values, nodes, lut_rgba):
    """Map data values to RGBA using the stretch and an (N,4) uint8 LUT.
    NaN pixels become fully transparent."""
    valid = np.isfinite(values)
    t = evaluate(nodes, np.where(valid, values, nodes[0][0]))
    idx = np.rint(t * (len(lut_rgba) - 1)).astype(np.int64)
    rgba = lut_rgba[idx]
    rgba[~valid] = 0
    return rgba


def flatten(rgba, bg_rgb):
    """Composite RGBA over a background colour -> RGB uint8."""
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32) * a + np.asarray(bg_rgb, np.float32) * (1.0 - a)
    return np.rint(rgb).astype(np.uint8)
