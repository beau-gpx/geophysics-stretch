# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Stretch Editor: ER Mapper-style interactive colour stretch for single-band rasters in QGIS."""

def classFactory(iface):
    from .plugin import StretchEditorPlugin
    return StretchEditorPlugin(iface)
