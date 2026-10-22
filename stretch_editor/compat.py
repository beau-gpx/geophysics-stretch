# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Small helpers that let the same code run on QGIS 3 (Qt5) and QGIS 4 (Qt6).

Qt6 only accepts scoped enum names (Qt.MouseButton.LeftButton) while older PyQt5 builds only
have the short form (Qt.LeftButton); QGIS has also moved several enums into the Qgis class.
"""


def E(obj, path):
    """Qt enum by scoped name, falling back to the unscoped name: E(Qt, 'MouseButton.LeftButton')."""
    scope, name = path.split('.')
    try:
        return getattr(getattr(obj, scope), name)
    except AttributeError:
        return getattr(obj, name)


def first_attr(*candidates):
    """The first (object, 'dotted.path') pair that resolves, e.g. a QGIS enum that moved
    between versions: first_attr((Qgis, 'LayerFilter.RasterLayer'), (QgsMapLayerProxyModel, 'RasterLayer'))."""
    for obj, path in candidates:
        try:
            cur = obj
            for part in path.split('.'):
                cur = getattr(cur, part)
            return cur
        except AttributeError:
            continue
    raise AttributeError(f'none of these exist: {[p for _, p in candidates]}')


def event_pos(event):
    """(x, y) of a mouse or wheel event (Qt6 position() / Qt5 pos())."""
    if hasattr(event, 'position'):
        p = event.position()
        return p.x(), p.y()
    p = event.pos()
    return float(p.x()), float(p.y())
