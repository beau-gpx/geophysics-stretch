# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Colour bar (legend) for a stretch: tick maths (pure numpy) and Qt rendering to PNG/SVG/PDF."""
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


# ------------------------------------------------------------- rendering (Qt)
def _qt():
    try:
        from qgis.PyQt import QtCore, QtGui
    except ImportError:
        from PyQt5 import QtCore, QtGui
    return QtCore, QtGui


def _E(obj, path):
    scope, name = path.split('.')
    try:
        return getattr(getattr(obj, scope), name)
    except AttributeError:
        return getattr(obj, name)


def _font(s, QtGui, bold=False):
    f = QtGui.QFont()
    f.setPixelSize(s['font_px'])
    f.setBold(bold)
    return f


def layout(s, title, info):
    """Size (w, h) of the colour bar image in logical pixels, plus label strings."""
    QtCore, QtGui = _qt()
    dec = label_decimals(info['ticks'], s['decimals'])
    labels = [format_value(v, dec) for _, v in info['ticks']]
    fm = QtGui.QFontMetricsF(_font(s, QtGui))
    fmt_ = QtGui.QFontMetricsF(_font(s, QtGui, bold=True))
    head = title + (f' ({s["units"]})' if s['units'] else '')
    pad, tick = 10, 6
    lw = max(fm.horizontalAdvance(t) for t in labels) if labels else 0
    lh = fm.height()
    th = fmt_.height() if head else 0
    tw = fmt_.horizontalAdvance(head) if head else 0
    if s['orientation'] == 'vertical':
        w = pad + s['thickness'] + tick + 4 + lw + pad
        w = max(w, tw + 2 * pad)
        h = pad + (th + 6 if head else 0) + lh / 2 + s['length'] + lh / 2 + pad
    else:
        w = pad + lw / 2 + s['length'] + lw / 2 + pad
        w = max(w, tw + 2 * pad)
        h = pad + (th + 6 if head else 0) + s['thickness'] + tick + 2 + lh + pad
    return int(math.ceil(w)), int(math.ceil(h)), labels, head


def paint(p, s, title, info, colours, w, h, labels, head):
    """Draw the colour bar with QPainter p in a w x h logical area.
    colours: list of QColor sampling the ramp 0..1."""
    QtCore, QtGui = _qt()
    QPointF, QRectF = QtCore.QPointF, QtCore.QRectF
    if s['background'] == 'white':
        p.fillRect(QRectF(0, 0, w, h), QtGui.QColor(255, 255, 255))
    p.setRenderHint(_E(QtGui.QPainter, 'RenderHint.Antialiasing'), True)
    p.setRenderHint(_E(QtGui.QPainter, 'RenderHint.TextAntialiasing'), True)
    ink = QtGui.QColor(20, 20, 20)
    f, fb = _font(s, QtGui), _font(s, QtGui, bold=True)
    fm = QtGui.QFontMetricsF(f)
    pad, tick = 10, 6
    y = pad
    if head:
        p.setFont(fb)
        p.setPen(ink)
        p.drawText(QPointF(pad, y + QtGui.QFontMetricsF(fb).ascent()), head)
        y += QtGui.QFontMetricsF(fb).height() + 6
    n = len(colours)
    tmin, tmax = info['tmin'], info['tmax']

    def colour_at(frac):
        t = tmin + frac * (tmax - tmin)
        return colours[int(round(min(1.0, max(0.0, t)) * (n - 1)))]

    L, T = s['length'], s['thickness']
    p.setFont(f)
    if s['orientation'] == 'vertical':
        y0 = y + fm.height() / 2
        bar = QRectF(pad, y0, T, L)
        steps = int(L)
        for k in range(steps):
            p.fillRect(QRectF(bar.left(), bar.bottom() - k - 1, T, 1.0), colour_at((k + 0.5) / steps))
        p.setPen(QtGui.QPen(ink, 1))
        p.setBrush(_E(QtCore.Qt, 'BrushStyle.NoBrush'))
        p.drawRect(bar)
        for (pos, _), text in zip(info['ticks'], labels):
            ty = bar.bottom() - pos * L
            p.drawLine(QPointF(bar.right(), ty), QPointF(bar.right() + tick, ty))
            p.drawText(QPointF(bar.right() + tick + 4, ty + fm.ascent() / 2 - fm.descent() / 2), text)
    else:
        lw0 = fm.horizontalAdvance(labels[0]) if labels else 0
        lw1 = fm.horizontalAdvance(labels[-1]) if labels else 0
        x0 = pad + max(lw0, lw1) / 2
        bar = QRectF(x0, y, L, T)
        steps = int(L)
        for k in range(steps):
            p.fillRect(QRectF(bar.left() + k, bar.top(), 1.0, T), colour_at((k + 0.5) / steps))
        p.setPen(QtGui.QPen(ink, 1))
        p.setBrush(_E(QtCore.Qt, 'BrushStyle.NoBrush'))
        p.drawRect(bar)
        for (pos, _), text in zip(info['ticks'], labels):
            tx = bar.left() + pos * L
            p.drawLine(QPointF(tx, bar.bottom()), QPointF(tx, bar.bottom() + tick))
            p.drawText(QPointF(tx - fm.horizontalAdvance(text) / 2, bar.bottom() + tick + 2 + fm.ascent()), text)


def render_image(s, title, nodes, colours, scale=None):
    """QImage of the colour bar (used for PNG and the dialog preview)."""
    QtCore, QtGui = _qt()
    s = normalise(s)
    info = bar_ticks(nodes, s['ticks'], s['tick_mode'])
    w, h, labels, head = layout(s, title, info)
    sc = scale or s['scale']
    img = QtGui.QImage(w * sc, h * sc, _E(QtGui.QImage, 'Format.Format_ARGB32_Premultiplied'))
    img.fill(QtGui.QColor(0, 0, 0, 0))
    dpm = int(round(96 * sc / 0.0254))
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    p = QtGui.QPainter(img)
    p.scale(sc, sc)
    paint(p, s, title, info, colours, w, h, labels, head)
    p.end()
    return img


def save(path, s, title, nodes, colours):
    """Write the colour bar to PNG, SVG or PDF (by s['fmt'])."""
    QtCore, QtGui = _qt()
    s = normalise(s)
    if s['fmt'] == 'png':
        if not render_image(s, title, nodes, colours).save(path, 'PNG'):
            raise IOError(f'Could not write {path}')
        return
    info = bar_ticks(nodes, s['ticks'], s['tick_mode'])
    w, h, labels, head = layout(s, title, info)
    if s['fmt'] == 'svg':
        try:
            from qgis.PyQt.QtSvg import QSvgGenerator
        except ImportError:
            from PyQt5.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(QtCore.QSize(w, h))
        gen.setViewBox(QtCore.QRect(0, 0, w, h))
        gen.setResolution(96)
        gen.setTitle(head or 'Colour bar')
        p = QtGui.QPainter(gen)
        paint(p, s, title, info, colours, w, h, labels, head)
        p.end()
    else:
        writer = QtGui.QPdfWriter(path)
        writer.setResolution(96)
        size = QtCore.QSizeF(w * 72.0 / 96.0, h * 72.0 / 96.0)
        writer.setPageSize(QtGui.QPageSize(size, _E(QtGui.QPageSize, 'Unit.Point')))
        writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
        p = QtGui.QPainter(writer)
        paint(p, s, title, info, colours, w, h, labels, head)
        p.end()
