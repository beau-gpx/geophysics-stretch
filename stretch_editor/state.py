# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""The editor's settings saved with each layer (as a JSON custom property, so they travel
with the QGIS project and with saved .qml styles)."""
import json

PROPERTY = 'stretchEditor/state'


def load(layer):
    """Saved state dict for layer, or None. Older formats are upgraded."""
    try:
        state = json.loads(layer.customProperty(PROPERTY, '') or 'null')
    except Exception:
        return None
    if not isinstance(state, dict):
        return None
    clip = state.setdefault('clip', {})
    if 'lower' not in clip:                     # v1.1 stored one symmetric percentage
        p = clip.get('pct', 0.0)
        clip['lower'], clip['upper'] = p, 100.0 - p
    if 'view_mode' not in state:
        state['view_mode'] = 'free' if state.get('view') else 'data'
    return state


def save(layer, state):
    """Store state on the layer. A ramp that can't be serialised is dropped, not fatal."""
    try:
        text = json.dumps(state)
    except TypeError:
        state = dict(state, ramp={})
        text = json.dumps(state)
    layer.setCustomProperty(PROPERTY, text)
