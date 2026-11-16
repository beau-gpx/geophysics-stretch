# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Ternary (RGB) images from three grids, e.g. radiometric K, Th and U as red, green and blue.

A ternary layer is a GDAL virtual raster (VRT): three Byte bands that read the source grids
through a lookup table (LUT) holding each channel's stretch curve. GDAL applies the curves, so
QGIS (or any GDAL-based GIS) draws the image natively and the plugin only rewrites the small
VRT file when a curve changes. Output values are 1..255 with 0 as nodata, so a pixel with
nodata in any channel is transparent. The plugin's settings are embedded in the VRT metadata.

Pure Python + numpy (no QGIS), so it can be unit tested.
"""
import json
import math
import os
import re
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from . import stretch

CHANNELS = ('Red', 'Green', 'Blue')
METADATA_KEY = 'SDP_IMAGING_TERNARY'
DUMMY_LIMIT = 1e30          # |value| beyond this is a dummy value: transparent, as in single-band mode

# name patterns for guessing K / Th / U layers (checked in this order: K, Th, U -> R, G, B)
_GUESS = [r'(^|[^a-z])(k|k_?pct|potassium|pot)([^a-z]|$)',
          r'(^|[^a-z])(th|eth|th_?ppm|thorium)([^a-z]|$)',
          r'(^|[^a-z])(u|eu|u_?ppm|uranium)([^a-z]|$)']


def guess_channels(names):
    """Indices into names for K, Th and U (red, green, blue), or None where nothing matches."""
    out = []
    for pat in _GUESS:
        hit = None
        for i, n in enumerate(names):
            if i not in out and re.search(pat, n.lower().replace('-', '_')):
                hit = i
                break
        out.append(hit)
    return out


# ------------------------------------------------------------- common grid
def common_grid(grids):
    """Target grid covering all sources: union extent at the finest cell size.
    grids: [{'gt': (x0, px, 0, y0, 0, -py), 'w': cols, 'h': rows}].
    Returns (gt, width, height, dst_rects) where dst_rects[i] = (xoff, yoff, xsize, ysize) in
    target pixels (fractional is fine for GDAL). Raises ValueError for rotated grids."""
    for g in grids:
        gt = g['gt']
        if gt[2] or gt[4] or not gt[1] > 0 or not gt[5] < 0:
            raise ValueError('rotated or flipped grids are not supported')
    xmin = min(g['gt'][0] for g in grids)
    ymax = max(g['gt'][3] for g in grids)
    xmax = max(g['gt'][0] + g['w'] * g['gt'][1] for g in grids)
    ymin = min(g['gt'][3] + g['h'] * g['gt'][5] for g in grids)
    cx = min(g['gt'][1] for g in grids)
    cy = min(-g['gt'][5] for g in grids)
    w = max(1, int(math.ceil((xmax - xmin) / cx - 1e-6)))
    h = max(1, int(math.ceil((ymax - ymin) / cy - 1e-6)))
    rects = [((g['gt'][0] - xmin) / cx, (ymax - g['gt'][3]) / cy,
              g['w'] * g['gt'][1] / cx, g['h'] * -g['gt'][5] / cy) for g in grids]
    return (xmin, cx, 0.0, ymax, 0.0, -cy), w, h, rects


# ------------------------------------------------------------- curves -> lookup tables
def lut_text(nodes, invert=False):
    """GDAL VRT <LUT> for a stretch curve: data value -> 1..255 (0 is kept for nodata).
    Values beyond the end nodes are held at the end outputs (GDAL clamps); dummy values beyond
    ±1e30 map to 0 so they are transparent."""
    nodes = stretch.sanitize(nodes)

    def out(y):
        y = 1.0 - y if invert else y
        return f'{1.0 + 254.0 * y:.4f}'.rstrip('0').rstrip('.')

    pairs = []
    if nodes[0][0] > -DUMMY_LIMIT:
        pairs += [(-DUMMY_LIMIT * 1.000001, '0'), (-DUMMY_LIMIT, out(nodes[0][1]))]
    pairs += [(x, out(y)) for x, y in nodes]
    if nodes[-1][0] < DUMMY_LIMIT:
        pairs += [(DUMMY_LIMIT, out(nodes[-1][1])), (DUMMY_LIMIT * 1.000001, '0')]
    return ','.join(f'{x!r}:{y}' for x, y in pairs)


def channel_colours(i, invert=False, n=256):
    """(n, 3) uint8 colours one channel produces on its own, from output 0 to 1:
    black -> red/green/blue, or for CMY white -> cyan/magenta/yellow."""
    t = np.linspace(0.0, 1.0, n)
    rgb = np.zeros((n, 3))
    rgb[:, i] = t
    if invert:
        rgb = 1.0 - rgb
    return np.rint(rgb * 255).astype(np.uint8)


# ------------------------------------------------------------- VRT
def vrt_xml(target, sources, curves, invert=False, settings=None, vrt_path=None):
    """VRT text for a ternary image.
    target: (gt, width, height, dst_rects) from common_grid; sources: three dicts with 'path',
    'band', 'w', 'h', 'nodata' (or None), 'wkt'; curves: three node lists; settings: dict stored
    in the metadata. Paths are written relative to the VRT where possible."""
    gt, width, height, rects = target
    bands = []
    for i, (src, nodes, rect) in enumerate(zip(sources, curves, rects)):
        path, rel = src['path'], '0'
        if vrt_path:
            try:
                path, rel = os.path.relpath(src['path'], os.path.dirname(os.path.abspath(vrt_path))), '1'
            except ValueError:              # another drive on Windows: keep it absolute
                pass
        nodata = '' if src.get('nodata') is None else f'<NODATA>{float(src["nodata"])!r}</NODATA>'
        bands.append(
            f'  <VRTRasterBand dataType="Byte" band="{i + 1}">\n'
            f'    <Description>{escape(src.get("name", CHANNELS[i]))}</Description>\n'
            f'    <NoDataValue>0</NoDataValue>\n'
            f'    <ColorInterp>{CHANNELS[i]}</ColorInterp>\n'
            f'    <ComplexSource resampling="bilinear">\n'
            f'      <SourceFilename relativeToVRT="{rel}">{escape(path)}</SourceFilename>\n'
            f'      <SourceBand>{int(src["band"])}</SourceBand>\n'
            f'      <SrcRect xOff="0" yOff="0" xSize="{src["w"]}" ySize="{src["h"]}"/>\n'
            f'      <DstRect xOff="{rect[0]!r}" yOff="{rect[1]!r}" xSize="{rect[2]!r}" ySize="{rect[3]!r}"/>\n'
            f'      {nodata}\n'
            f'      <LUT>{lut_text(nodes, invert)}</LUT>\n'
            f'    </ComplexSource>\n'
            f'  </VRTRasterBand>\n')
    meta = ''
    if settings is not None:
        meta = (f'  <Metadata>\n    <MDI key={quoteattr(METADATA_KEY)}>{escape(json.dumps(settings))}</MDI>\n'
                f'  </Metadata>\n')
    srs = f'  <SRS>{escape(sources[0]["wkt"])}</SRS>\n' if sources[0].get('wkt') else ''
    return (f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">\n{srs}'
            f'  <GeoTransform>{", ".join(repr(float(v)) for v in gt)}</GeoTransform>\n'
            f'{meta}{"".join(bands)}</VRTDataset>\n')


def read_settings(vrt_text):
    """The plugin settings embedded in a ternary VRT, or None."""
    try:
        root = ElementTree.fromstring(vrt_text)
    except ElementTree.ParseError:
        return None
    for mdi in root.iter('MDI'):
        if mdi.get('key') == METADATA_KEY:
            try:
                d = json.loads(mdi.text or '')
            except ValueError:
                return None
            return d if isinstance(d, dict) and len(d.get('channels', [])) == 3 else None
    return None


# ------------------------------------------------------------- rendering (export)
def render(values, curves, invert=False):
    """RGBA uint8 for three arrays of data values (NaN = nodata) and their curves.
    A pixel with nodata in any channel is fully transparent."""
    valid = np.ones(values[0].shape, bool)
    rgba = np.zeros(values[0].shape + (4,), np.uint8)
    for i, (v, nodes) in enumerate(zip(values, curves)):
        ok = np.isfinite(v)
        valid &= ok
        t = stretch.evaluate(nodes, np.where(ok, v, nodes[0][0]))
        if invert:
            t = 1.0 - t
        rgba[..., i] = np.rint(t * 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0)
    rgba[~valid, :3] = 0
    return rgba


def triangle(size, invert=False):
    """(size, size, 4) uint8 ternary legend: an equilateral triangle with red at the top,
    green bottom-left and blue bottom-right. Each point's colour is its barycentric weights
    scaled so the largest is full intensity (white in the middle, or black for CMY)."""
    h = size * math.sqrt(3) / 2
    top, bl, br = (size / 2, (size - h) / 2), (0.0, (size + h) / 2), (float(size), (size + h) / 2)
    yy, xx = np.mgrid[0:size, 0:size] + 0.5
    den = (bl[1] - br[1]) * (top[0] - br[0]) + (br[0] - bl[0]) * (top[1] - br[1])
    a = ((bl[1] - br[1]) * (xx - br[0]) + (br[0] - bl[0]) * (yy - br[1])) / den
    b = ((br[1] - top[1]) * (xx - br[0]) + (top[0] - br[0]) * (yy - br[1])) / den
    c = 1.0 - a - b
    w = np.stack([a, b, c], -1)
    inside = (w >= -1e-9).all(-1)
    w = np.clip(w, 0, 1)
    w = w / np.maximum(w.max(-1, keepdims=True), 1e-9)
    if invert:
        w = 1.0 - w
    img = np.zeros((size, size, 4), np.uint8)
    img[..., :3] = np.rint(w * 255).astype(np.uint8)
    img[..., 3] = np.where(inside, 255, 0)
    img[~inside, :3] = 0
    return img, (top, bl, br)
