# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Colour ramps, and turning a stretch curve into a QGIS layer style."""
import numpy as np
from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

from .compat import first_attr
from .core import stretch

LUT_SIZE = 1024         # colour lookup resolution
SHADER_ITEMS = 512      # colour stops written to the layer style


def default_ramp():
    """ER Mapper-style pseudocolour: blue, cyan, green, yellow, red, magenta."""
    stops = [QgsGradientStop(0.2, QColor(0, 200, 255)), QgsGradientStop(0.4, QColor(0, 220, 0)),
             QgsGradientStop(0.6, QColor(255, 255, 0)), QgsGradientStop(0.8, QColor(255, 0, 0))]
    return QgsGradientColorRamp(QColor(0, 0, 255), QColor(255, 0, 255), False, stops)


def colour_lut(ramp):
    """Sample a colour ramp: (list of QColor, (N, 4) uint8 RGBA array)."""
    ramp = ramp or default_ramp()
    colours = [ramp.color(i / (LUT_SIZE - 1)) for i in range(LUT_SIZE)]
    rgba = np.array([[c.red(), c.green(), c.blue(), c.alpha()] for c in colours], dtype=np.uint8)
    return colours, rgba


def ramp_to_dict(ramp):
    """JSON-friendly description of a colour ramp (for saving with the layer)."""
    try:
        from qgis.core import QgsSymbolLayerUtils
        return {'variant': QgsSymbolLayerUtils.colorRampToVariant('r', ramp)}
    except Exception:
        return {'type': ramp.type(), 'props': ramp.properties()}


def ramp_from_dict(d):
    """Colour ramp from ramp_to_dict(), or None."""
    try:
        if 'variant' in d:
            from qgis.core import QgsSymbolLayerUtils
            r = QgsSymbolLayerUtils.loadColorRamp(d['variant'])
            if r:
                return r
        if d.get('type') == 'gradient':
            return QgsGradientColorRamp.create(d['props'])
    except Exception:
        pass
    return None


def _interpolated():
    return first_attr((Qgis, 'ShaderInterpolationMethod.Linear'), (QgsColorRampShader, 'Type.Interpolated'),
                      (QgsColorRampShader, 'Interpolated'))


def apply_stretch(layer, band, nodes, colours, ramp=None):
    """Style layer as a single-band pseudocolour that reproduces the stretch curve exactly.
    colours: QColor list from colour_lut(); ramp: kept as the style's source ramp for editing."""
    x0, x1 = nodes[0][0], nodes[-1][0]
    values = np.unique(np.concatenate([np.linspace(x0, x1, SHADER_ITEMS), [n[0] for n in nodes]]))
    outputs = stretch.evaluate(nodes, values)
    last = len(colours) - 1
    items = [QgsColorRampShader.ColorRampItem(float(v), colours[int(round(t * last))], '')
             for v, t in zip(values, outputs)]

    shader = QgsColorRampShader()
    shader.setColorRampType(_interpolated())
    shader.setColorRampItemList(items)
    shader.setMinimumValue(x0)
    shader.setMaximumValue(x1)
    shader.setClip(False)                 # values beyond the ends take the end colours
    try:
        if ramp:
            shader.setSourceColorRamp(ramp)
    except Exception:
        pass
    try:                                  # continuous legend in the Layers panel and layouts
        from qgis.core import QgsColorRampLegendNodeSettings
        legend = QgsColorRampLegendNodeSettings()
        legend.setUseContinuousLegend(True)
        shader.setLegendSettings(legend)
    except Exception:
        pass

    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), band, raster_shader)
    renderer.setClassificationMin(x0)
    renderer.setClassificationMax(x1)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    try:
        layer.emitStyleChanged()
    except Exception:
        pass
