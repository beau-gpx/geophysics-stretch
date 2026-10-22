# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
def classFactory(iface):
    from .plugin import StretchEditorPlugin
    return StretchEditorPlugin(iface)
