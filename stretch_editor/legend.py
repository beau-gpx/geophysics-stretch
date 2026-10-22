# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Draw a colour bar (legend) for a stretch with Qt and save it as PNG, SVG or PDF.

Label positions and values come from core.colourbar; this module only lays out and paints.
"""
import math

from qgis.PyQt.QtCore import QMarginsF, QPointF, QRect, QRectF, QSize, QSizeF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QImage, QPageSize, QPainter, QPdfWriter, QPen

from .compat import E
from .core import colourbar as cb

PAD = 10        # px around the bar
TICK = 6        # px tick length
INK = QColor(20, 20, 20)


def _font(s, bold=False):
    f = QFont()
    f.setPixelSize(s['font_px'])
    f.setBold(bold)
    return f


def layout(s, title, info):
    """Image size (w, h) in logical pixels, the label strings and the heading."""
    labels = cb.labels(info['ticks'], s['decimals'])
    fm, fmb = QFontMetricsF(_font(s)), QFontMetricsF(_font(s, bold=True))
    head = title + (f' ({s["units"]})' if s['units'] else '')
    lw = max((fm.horizontalAdvance(t) for t in labels), default=0)
    lh = fm.height()
    head_h = fmb.height() + 6 if head else 0
    head_w = fmb.horizontalAdvance(head) if head else 0
    if s['orientation'] == 'vertical':
        w = PAD + s['thickness'] + TICK + 4 + lw + PAD
        h = PAD + head_h + lh / 2 + s['length'] + lh / 2 + PAD
    else:
        w = PAD + lw / 2 + s['length'] + lw / 2 + PAD
        h = PAD + head_h + s['thickness'] + TICK + 2 + lh + PAD
    w = max(w, head_w + 2 * PAD)
    return int(math.ceil(w)), int(math.ceil(h)), labels, head


def paint(p, s, info, colours, w, h, labels, head):
    """Draw the colour bar with QPainter p into a w x h logical area.
    colours: list of QColor sampling the ramp from 0 to 1."""
    if s['background'] == 'white':
        p.fillRect(QRectF(0, 0, w, h), QColor(255, 255, 255))
    p.setRenderHint(E(QPainter, 'RenderHint.Antialiasing'), True)
    p.setRenderHint(E(QPainter, 'RenderHint.TextAntialiasing'), True)
    f, fb = _font(s), _font(s, bold=True)
    fm = QFontMetricsF(f)

    y = PAD
    if head:
        fmb = QFontMetricsF(fb)
        p.setFont(fb)
        p.setPen(INK)
        p.drawText(QPointF(PAD, y + fmb.ascent()), head)
        y += fmb.height() + 6

    n = len(colours)
    tmin, tmax = info['tmin'], info['tmax']

    def colour_at(frac):
        t = min(1.0, max(0.0, tmin + frac * (tmax - tmin)))
        return colours[int(round(t * (n - 1)))]

    length, thick = s['length'], s['thickness']
    p.setFont(f)
    if s['orientation'] == 'vertical':
        bar = QRectF(PAD, y + fm.height() / 2, thick, length)
        for k in range(int(length)):
            p.fillRect(QRectF(bar.left(), bar.bottom() - k - 1, thick, 1.0), colour_at((k + 0.5) / length))
    else:
        lw = max(fm.horizontalAdvance(labels[0]), fm.horizontalAdvance(labels[-1])) if labels else 0
        bar = QRectF(PAD + lw / 2, y, length, thick)
        for k in range(int(length)):
            p.fillRect(QRectF(bar.left() + k, bar.top(), 1.0, thick), colour_at((k + 0.5) / length))

    p.setPen(QPen(INK, 1))
    p.setBrush(E(Qt, 'BrushStyle.NoBrush'))
    p.drawRect(bar)
    for (pos, _), text in zip(info['ticks'], labels):
        if s['orientation'] == 'vertical':
            ty = bar.bottom() - pos * length
            p.drawLine(QPointF(bar.right(), ty), QPointF(bar.right() + TICK, ty))
            p.drawText(QPointF(bar.right() + TICK + 4, ty + fm.ascent() / 2 - fm.descent() / 2), text)
        else:
            tx = bar.left() + pos * length
            p.drawLine(QPointF(tx, bar.bottom()), QPointF(tx, bar.bottom() + TICK))
            p.drawText(QPointF(tx - fm.horizontalAdvance(text) / 2, bar.bottom() + TICK + 2 + fm.ascent()), text)


def render_image(s, title, nodes, colours, scale=None):
    """QImage of the colour bar (used for PNG output and the dialog preview)."""
    s = cb.normalise(s)
    info = cb.bar_ticks(nodes, s['ticks'], s['tick_mode'])
    w, h, labels, head = layout(s, title, info)
    sc = scale or s['scale']
    img = QImage(w * sc, h * sc, E(QImage, 'Format.Format_ARGB32_Premultiplied'))
    img.fill(QColor(0, 0, 0, 0))
    dpm = int(round(96 * sc / 0.0254))
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    p = QPainter(img)
    p.scale(sc, sc)
    paint(p, s, info, colours, w, h, labels, head)
    p.end()
    return img


def save(path, s, title, nodes, colours):
    """Write the colour bar to PNG, SVG or PDF (chosen by s['fmt'])."""
    s = cb.normalise(s)
    if s['fmt'] == 'png':
        if not render_image(s, title, nodes, colours).save(path, 'PNG'):
            raise OSError(f'Could not write {path}')
        return
    info = cb.bar_ticks(nodes, s['ticks'], s['tick_mode'])
    w, h, labels, head = layout(s, title, info)
    if s['fmt'] == 'svg':
        from qgis.PyQt.QtSvg import QSvgGenerator  # imported here: QtSvg is an optional module
        device = QSvgGenerator()
        device.setFileName(path)
        device.setSize(QSize(w, h))
        device.setViewBox(QRect(0, 0, w, h))
        device.setResolution(96)
        device.setTitle(head or 'Colour bar')
    else:
        device = QPdfWriter(path)
        device.setResolution(96)
        device.setPageSize(QPageSize(QSizeF(w * 72.0 / 96.0, h * 72.0 / 96.0), E(QPageSize, 'Unit.Point')))
        device.setPageMargins(QMarginsF(0, 0, 0, 0))
    p = QPainter(device)
    paint(p, s, info, colours, w, h, labels, head)
    p.end()
