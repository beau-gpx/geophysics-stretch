# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""The Stretch Editor panel: layer/band choice, curve editing, clip limits, mirror mode,
undo/redo, live styling, and image / colour bar / style export."""
import copy
import os

import numpy as np
from qgis.core import QgsRasterLayer, QgsRectangle
from qgis.gui import QgsCollapsibleGroupBox, QgsColorRampButton, QgsMapLayerComboBox, QgsRasterBandComboBox
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import layers, legend, state, styling
from ..compat import E
from ..core import export, stretch
from .colourbar_dialog import ColourBarDialog
from .colourbar_dialog import stored_settings as colourbar_settings
from .curve_widget import CurveWidget
from .export_dialog import ExportDialog

TITLE = 'Stretch Editor'
SAMPLE_MAX = 1200               # histogram sample: max pixels on the long side
HISTORY_MAX = 200               # undo steps kept
DEFAULT_POINTS = {'linear': 32, 'histeq': 32, 'log': 32}
LIVE_DELAY_MS = 150             # live update waits this long after the last change


def _value_spin():
    """Spin box for data values (wide range, updates on Enter or arrows only)."""
    sb = QDoubleSpinBox()
    sb.setRange(-1e15, 1e15)
    sb.setDecimals(6)
    sb.setKeyboardTracking(False)
    return sb


def _tool(text, tip):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    return b


def _set_quiet(widget, value):
    """Set a spin box value, combo box data or check box without emitting signals."""
    widget.blockSignals(True)
    if isinstance(widget, QComboBox):
        i = widget.findData(value)
        if i >= 0:
            widget.setCurrentIndex(i)
    elif isinstance(widget, (QCheckBox, QToolButton)):
        widget.setChecked(bool(value))
    else:
        widget.setValue(value)
    widget.blockSignals(False)


class StretchDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__(TITLE, parent)
        self.iface = iface
        self.setObjectName('StretchEditorDock')

        self.layer = None
        self.sample = None              # valid band values used for the histogram and presets
        self.last_preset = 'linear'
        self.edited = False             # curve hand-edited since the last preset
        self.preset_points = dict(DEFAULT_POINTS)
        self.view_mode = 'data'         # 'data' | 'curve' | 'free' (zoomed, panned or typed)
        self.history, self.hpos = [], -1
        self._loading = False           # True while a grid is being opened
        self._syncing = False           # True while syncing with the Layers panel
        self._centre_prev = 0.0
        self._slope_prev = 1.0

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(LIVE_DELAY_MS)
        self.timer.timeout.connect(self.apply)

        self._build_ui()
        self._connect()

        self.on_clip_mode()
        self.update_mirror_widgets()
        self.update_lut()
        self.update_undo_buttons()
        active = self.iface.activeLayer()      # open on the grid already selected in the Layers panel
        if isinstance(active, QgsRasterLayer):
            self.layerCombo.blockSignals(True)
            self.layerCombo.setLayer(active)
            self.layerCombo.blockSignals(False)
        self.on_layer(self.layerCombo.currentLayer())

    # ================================================================ layout
    def _build_ui(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # layer / band
        g = QGridLayout()
        g.addWidget(QLabel('Layer'), 0, 0)
        self.layerCombo = QgsMapLayerComboBox()
        self.layerCombo.setFilters(layers.raster_layer_filter())
        g.addWidget(self.layerCombo, 0, 1)
        g.addWidget(QLabel('Band'), 1, 0)
        self.bandCombo = QgsRasterBandComboBox()
        g.addWidget(self.bandCombo, 1, 1)
        self.chkSync = QCheckBox('Sync with Layers panel')
        self.chkSync.setChecked(True)
        self.chkSync.setToolTip('Picking a grid here selects it in the Layers panel (expanding its group),\n'
                                'and selecting a raster in the Layers panel opens it here.')
        g.addWidget(self.chkSync, 2, 1)
        lay.addLayout(g)

        # curve editor + undo/redo
        self.curve = CurveWidget()
        lay.addWidget(self.curve)
        row = QHBoxLayout()
        hint = QLabel('Click add · drag move (onto a node to merge) · right-click delete · '
                      'Shift+wheel zoom · Shift-drag pan')
        hint.setStyleSheet('color: gray; font-size: 8pt;')
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        self.btnUndo = _tool('↶ Undo', 'Undo curve change (Ctrl+Z with the curve focused)')
        self.btnRedo = _tool('↷ Redo', 'Redo curve change (Ctrl+Y / Ctrl+Shift+Z)')
        row.addWidget(self.btnUndo)
        row.addWidget(self.btnRedo)
        lay.addLayout(row)

        # view range
        row = QHBoxLayout()
        row.addWidget(QLabel('View'))
        self.viewLo, self.viewHi = _value_spin(), _value_spin()
        self.viewLo.setToolTip('Left edge of the histogram (data value)')
        self.viewHi.setToolTip('Right edge of the histogram (data value)')
        row.addWidget(self.viewLo, 1)
        row.addWidget(QLabel('to'))
        row.addWidget(self.viewHi, 1)
        self.btnViewData = _tool('Data', 'Show the full data range (min to max)')
        self.btnViewCurve = _tool('Curve', 'Fit the view to the curve nodes, and keep it fitted\n'
                                           'when the clip limits change')
        for b in (self.btnViewData, self.btnViewCurve):
            b.setCheckable(True)
            row.addWidget(b)
        lay.addLayout(row)

        # presets, points, display options
        row = QHBoxLayout()
        self.btnLin = QPushButton('Linear')
        self.btnEq = QPushButton('Hist. equalise')
        self.btnLog = QPushButton('Log-linear')
        for b in (self.btnLin, self.btnEq, self.btnLog):
            row.addWidget(b)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel('Points'))
        self.points = QSpinBox()
        self.points.setRange(2, 256)
        self.points.setKeyboardTracking(False)
        self.points.setToolTip('Number of nodes on the curve.\n'
                               'Unedited preset: rebuilds the preset with this many points.\n'
                               'Edited curve: resamples it, keeping its shape.')
        row.addWidget(self.points)
        row.addStretch()
        self.chkLogHist = QCheckBox('Log counts (Y)')
        self.chkLogHist.setToolTip('Log-scale the histogram bar heights')
        self.chkLogX = QCheckBox('Log values (X)')
        self.chkLogX.setToolTip('Show data values on a log axis.\n'
                                'Data with zero or negative values uses a symmetric log (linear near zero).')
        row.addWidget(self.chkLogHist)
        row.addWidget(self.chkLogX)
        lay.addLayout(row)

        # clip limits
        box = QGroupBox('Clip limits')
        cg = QGridLayout(box)
        self.clipMode = QComboBox()
        self.clipMode.addItem('Percentile', 'pct')
        self.clipMode.addItem('Values', 'val')
        cg.addWidget(self.clipMode, 0, 0, 1, 3)
        self.btnClipReset = _tool('Reset', 'Reset to Percentile 0 % – 100 % (data minimum to maximum)')
        cg.addWidget(self.btnClipReset, 0, 3)
        self.pctLo, self.pctHi = QDoubleSpinBox(), QDoubleSpinBox()
        for sb, v in ((self.pctLo, 0.0), (self.pctHi, 100.0)):
            sb.setRange(0.0, 100.0)
            sb.setDecimals(2)
            sb.setSingleStep(0.5)
            sb.setSuffix(' %')
            sb.setKeyboardTracking(False)
            sb.setValue(v)
        self.pctLo.setToolTip('Lower limit as a percentile of the data (0 % = minimum)')
        self.pctHi.setToolTip('Upper limit as a percentile of the data (100 % = maximum)')
        self.lblPLo, self.lblPHi = QLabel('Lower'), QLabel('Upper')
        cg.addWidget(self.lblPLo, 1, 0)
        cg.addWidget(self.pctLo, 1, 1)
        cg.addWidget(self.lblPHi, 1, 2)
        cg.addWidget(self.pctHi, 1, 3)
        self.clipLo, self.clipHi = _value_spin(), _value_spin()
        self.lblLo, self.lblHi = QLabel('Min'), QLabel('Max')
        cg.addWidget(self.lblLo, 2, 0)
        cg.addWidget(self.clipLo, 2, 1)
        cg.addWidget(self.lblHi, 2, 2)
        cg.addWidget(self.clipHi, 2, 3)
        lay.addWidget(box)

        # advanced (collapsed): mirror the stretch about a centre value
        adv = QgsCollapsibleGroupBox('Advanced')
        adv.setCollapsed(True)
        ag = QGridLayout(adv)
        self.chkMirror = QCheckBox('Mirror about centre')
        self.chkMirror.setToolTip('Keep the stretch symmetric about the centre value (e.g. 0 for 1VD grids).\n'
                                  'The centre sits mid-ramp, equal positive and negative values get\n'
                                  'mirrored colours, and edits on one side are copied to the other.\n'
                                  'Clip limits become centre ± width (percentile mode uses the Upper %).')
        ag.addWidget(self.chkMirror, 0, 0, 1, 4)
        ag.addWidget(QLabel('Centre'), 1, 0)
        self.centre = _value_spin()
        ag.addWidget(self.centre, 1, 1)
        self.btnCentre0 = _tool('0', 'Centre on zero')
        self.btnCentreMed = _tool('Median', 'Centre on the data median')
        ag.addWidget(self.btnCentre0, 1, 2)
        ag.addWidget(self.btnCentreMed, 1, 3)
        self.lblWidth = QLabel('Width ±')
        self.widthSpin = _value_spin()
        self.widthSpin.setMinimum(0.0)
        self.widthSpin.setToolTip('Half-width of the stretch around the centre (clip limits = centre ± width)')
        ag.addWidget(self.lblWidth, 2, 0)
        ag.addWidget(self.widthSpin, 2, 1, 1, 3)
        self.lblSlope = QLabel('Slope')
        self.slope = QDoubleSpinBox()
        self.slope.setRange(0.2, 5.0)
        self.slope.setDecimals(2)
        self.slope.setSingleStep(0.1)
        self.slope.setValue(1.0)
        self.slope.setKeyboardTracking(False)
        self.slope.setToolTip('Contrast around the centre. 1 = the preset as is;\n'
                              'above 1 = steeper near the centre (small values stand out more);\n'
                              'below 1 = flatter near the centre (more contrast in the tails).')
        ag.addWidget(self.lblSlope, 3, 0)
        ag.addWidget(self.slope, 3, 1, 1, 3)
        lay.addWidget(adv)

        # selected node
        box = QGroupBox('Selected node')
        bg = QHBoxLayout(box)
        bg.addWidget(QLabel('Value'))
        self.spinVal = _value_spin()
        bg.addWidget(self.spinVal, 1)
        bg.addWidget(QLabel('Output %'))
        self.spinOut = QDoubleSpinBox()
        self.spinOut.setRange(0, 100)
        self.spinOut.setDecimals(1)
        self.spinOut.setKeyboardTracking(False)
        bg.addWidget(self.spinOut)
        box.setEnabled(False)
        self.nodeBox = box
        lay.addWidget(box)

        # colour ramp + apply
        row = QHBoxLayout()
        row.addWidget(QLabel('Colour ramp'))
        self.rampBtn = QgsColorRampButton()
        self.rampBtn.setDefaultColorRamp(styling.default_ramp())
        self.rampBtn.setColorRamp(styling.default_ramp())
        row.addWidget(self.rampBtn, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.chkLive = QCheckBox('Live update')
        self.chkLive.setChecked(True)
        self.btnApply = QPushButton('Apply')
        row.addWidget(self.chkLive)
        row.addStretch()
        row.addWidget(self.btnApply)
        lay.addLayout(row)

        # export
        row = QHBoxLayout()
        self.btnExport = QPushButton('Export image…')
        self.btnBar = QPushButton('Colour bar…')
        self.btnBar.setToolTip('Export a colour bar / legend for this stretch (PNG, SVG or PDF)')
        self.btnStyle = QPushButton('Save style…')
        self.btnStyle.setToolTip('Save the stretch as a QGIS style file (.qml)')
        for b in (self.btnExport, self.btnBar, self.btnStyle):
            row.addWidget(b)
        lay.addLayout(row)

        scroll = QScrollArea()                # the panel scrolls when the dock is shorter than it
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(E(QFrame, 'Shape.NoFrame'))
        self.setWidget(scroll)

    def _connect(self):
        c = self.curve
        c.curveChanged.connect(self.on_curve_changed)
        c.curveEdited.connect(self.on_user_edit)
        c.selectionChanged.connect(self.on_selection)
        c.viewChanged.connect(self.on_curve_view)
        c.undoRequested.connect(self.undo)            # Ctrl+Z / Ctrl+Y while the curve has focus
        c.redoRequested.connect(self.redo)
        self.layerCombo.layerChanged.connect(self.on_layer)
        self.bandCombo.bandChanged.connect(self.on_band)
        self.iface.currentLayerChanged.connect(self.on_active_layer)
        self.btnUndo.clicked.connect(self.undo)
        self.btnRedo.clicked.connect(self.redo)
        self.viewLo.valueChanged.connect(self.on_view_spin)
        self.viewHi.valueChanged.connect(self.on_view_spin)
        self.btnViewData.clicked.connect(self.view_data)
        self.btnViewCurve.clicked.connect(self.view_curve)
        self.btnLin.clicked.connect(lambda: self.preset('linear'))
        self.btnEq.clicked.connect(lambda: self.preset('histeq'))
        self.btnLog.clicked.connect(lambda: self.preset('log'))
        self.points.valueChanged.connect(self.on_points)
        self.chkLogHist.toggled.connect(self.on_log_hist)
        self.chkLogX.toggled.connect(self.on_log_x)
        self.clipMode.currentIndexChanged.connect(self.on_clip_mode)
        self.btnClipReset.clicked.connect(self.reset_clip)
        for sb in (self.pctLo, self.pctHi, self.clipLo, self.clipHi):
            sb.valueChanged.connect(self.on_clip)
        self.chkMirror.toggled.connect(self.on_mirror)
        self.centre.valueChanged.connect(self.on_centre)
        self.btnCentre0.clicked.connect(lambda: self.centre.setValue(0.0))
        self.btnCentreMed.clicked.connect(self.centre_on_median)
        self.widthSpin.valueChanged.connect(self.on_width)
        self.slope.valueChanged.connect(self.on_slope)
        self.spinVal.valueChanged.connect(self.on_spin)
        self.spinOut.valueChanged.connect(self.on_spin)
        self.rampBtn.colorRampChanged.connect(self.on_ramp)
        self.btnApply.clicked.connect(self.apply)
        self.btnExport.clicked.connect(self.export_image)
        self.btnBar.clicked.connect(self.export_colourbar)
        self.btnStyle.clicked.connect(self.save_style)

    def cleanup(self):
        """Disconnect from QGIS when the plugin unloads."""
        try:
            self.iface.currentLayerChanged.disconnect(self.on_active_layer)
        except Exception:
            pass

    # ================================================================ opening a grid
    def on_layer(self, layer):
        self.layer = layer if isinstance(layer, QgsRasterLayer) else None
        self.bandCombo.setLayer(self.layer)
        self.on_band(self.bandCombo.currentBand())
        if self.layer is not None and self.chkSync.isChecked():
            self.show_in_layers_panel(self.layer)

    def on_band(self, band):
        """Load a band: sample it, restore its saved stretch (or start from its current style).
        Opening a grid never restyles it; the first edit or Apply does."""
        self.sample = None
        if self.layer is None or band is None or band < 1:
            self.curve.set_sample(None)
            self.curve.set_nodes([])
            self.reset_history()
            return
        try:
            s = layers.sample_band(self.layer, band, SAMPLE_MAX)
        except Exception as e:
            QMessageBox.warning(self, TITLE, f'Could not read band: {e}')
            return
        self.sample = s

        self._loading = True
        dlo, dhi = stretch.data_range(s)
        step = (dhi - dlo) / 200.0 or 1.0
        for sb in (self.clipLo, self.clipHi, self.spinVal, self.viewLo, self.viewHi, self.centre):
            sb.setSingleStep(step)
        self.curve.set_sample(s)

        saved = state.load(self.layer)
        same_band = bool(saved) and saved.get('band') == band
        disp = (saved or {}).get('display', {})
        _set_quiet(self.chkLogHist, disp.get('log_counts', self.chkLogHist.isChecked()))
        _set_quiet(self.chkLogX, disp.get('log_x', self.chkLogX.isChecked()))
        self.curve.set_log_hist(self.chkLogHist.isChecked())
        self.curve.set_xlog(self.chkLogX.isChecked())

        mirror = saved.get('mirror', {}) if same_band else {}
        _set_quiet(self.centre, mirror.get('centre', 0.0))
        _set_quiet(self.chkMirror, mirror.get('on', False))
        _set_quiet(self.slope, mirror.get('slope', 1.0))
        self._centre_prev, self._slope_prev = self.centre.value(), self.slope.value()
        self.curve.set_mirror(self.centre.value() if self.chkMirror.isChecked() else None)

        if same_band and len(saved.get('nodes', [])) >= 2:
            ramp = styling.ramp_from_dict(saved.get('ramp', {}))
            if ramp:
                self.rampBtn.setColorRamp(ramp)
            self.last_preset = saved.get('preset', 'linear')
            self.edited = bool(saved.get('edited', True))
            self.preset_points.update(saved.get('preset_points', {}))
            clip = saved['clip']
            _set_quiet(self.pctLo, clip['lower'])
            _set_quiet(self.pctHi, clip['upper'])
            _set_quiet(self.clipMode, 'val' if clip.get('mode') == 'val' else 'pct')
            nodes = saved['nodes']
            _set_quiet(self.clipLo, clip.get('lo', nodes[0][0]))
            _set_quiet(self.clipHi, clip.get('hi', nodes[-1][0]))
            self.curve.set_nodes(nodes)
            view, view_mode = saved.get('view') or (dlo, dhi), saved['view_mode']
        else:
            self.last_preset, self.edited = 'linear', False
            current = layers.existing_stretch_range(self.layer, band)
            if current:                       # start from the stretch the layer already has
                lo, hi = current
                _set_quiet(self.clipMode, 'val')
            else:
                lo, hi = stretch.percent_clip(s, self.pctLo.value(), self.pctHi.value())
            _set_quiet(self.clipLo, lo)
            _set_quiet(self.clipHi, hi)
            self.curve.set_nodes(self._run_preset('linear'))
            view, view_mode = (dlo, dhi), 'data'

        self.on_clip_mode(fill=False)
        self.update_mirror_widgets()
        self.set_view(*view, view_mode)
        self.sync_points()
        self._loading = False
        self.reset_history()
        self.update_lut()

    # ================================================================ Layers panel sync
    def show_in_layers_panel(self, layer):
        if self._syncing:
            return
        self._syncing = True
        try:
            layers.show_in_layers_panel(self.iface, layer)
        except Exception:
            pass
        finally:
            self._syncing = False

    def on_active_layer(self, layer):
        if self._syncing or not self.chkSync.isChecked():
            return
        if isinstance(layer, QgsRasterLayer) and layer is not self.layer:
            self._syncing = True
            try:
                self.layerCombo.setLayer(layer)
            finally:
                self._syncing = False

    # ================================================================ histogram display
    def on_log_hist(self, on):
        self.curve.set_log_hist(on)
        self.save_state()

    def on_log_x(self, on):
        self.curve.set_xlog(on)
        self.on_curve_view(self.curve.lo, self.curve.hi)

    def set_view(self, lo, hi, mode=None):
        if mode:
            self.set_view_mode(mode)
        self.curve.set_view(lo, hi)
        _set_quiet(self.viewLo, self.curve.lo)
        _set_quiet(self.viewHi, self.curve.hi)
        self.save_state()

    def set_view_mode(self, mode):
        self.view_mode = mode
        _set_quiet(self.btnViewData, mode == 'data')
        _set_quiet(self.btnViewCurve, mode == 'curve')

    def on_curve_view(self, lo, hi):          # zoomed or panned in the editor
        self.set_view_mode('free')
        _set_quiet(self.viewLo, lo)
        _set_quiet(self.viewHi, hi)
        self.save_state()

    def on_view_spin(self, *_):
        if self.viewHi.value() > self.viewLo.value():
            self.set_view(self.viewLo.value(), self.viewHi.value(), 'free')

    def view_data(self):
        if self.sample is not None:
            self.set_view(*stretch.data_range(self.sample), 'data')

    def view_curve(self):
        if len(self.curve.nodes) >= 2:
            self.set_view(*stretch.fit_curve_view(self.curve.nodes), 'curve')

    def follow_curve(self):
        """In Curve view, re-fit the x-axis after the curve's ends move."""
        if self.view_mode == 'curve' and len(self.curve.nodes) >= 2:
            self.set_view(*stretch.fit_curve_view(self.curve.nodes))

    # ================================================================ clip limits
    def mirroring(self):
        return self.chkMirror.isChecked() and self.sample is not None

    def clip_range(self):
        """(lo, hi) data limits from the clip settings (centre ± width in mirror mode)."""
        if self.mirroring():
            c = self.centre.value()
            if self.clipMode.currentData() == 'val':
                r = max(abs(self.clipLo.value() - c), abs(self.clipHi.value() - c)) or 1e-9
            else:
                r = stretch.mirror_radius(self.sample, c, self.pctHi.value())
            return c - r, c + r
        if self.clipMode.currentData() == 'val':
            lo, hi = sorted((self.clipLo.value(), self.clipHi.value()))
            if hi == lo:
                hi = lo + max(abs(lo) * 1e-6, 1e-9)
            return lo, hi
        return stretch.percent_clip(self.sample, self.pctLo.value(), self.pctHi.value())

    def on_clip_mode(self, *_, fill=True):
        manual = self.clipMode.currentData() == 'val'
        for wdg in (self.pctHi, self.lblPHi):
            wdg.setEnabled(not manual)
        for wdg in (self.pctLo, self.lblPLo):          # mirror mode only uses the upper percentile
            wdg.setEnabled(not manual and not self.chkMirror.isChecked())
        for wdg in (self.clipLo, self.clipHi, self.lblLo, self.lblHi):
            wdg.setEnabled(manual)
        if manual and fill and len(self.curve.nodes) >= 2 and not self._loading:
            _set_quiet(self.clipLo, self.curve.nodes[0][0])     # start from what is applied
            _set_quiet(self.clipHi, self.curve.nodes[-1][0])
        if not self._loading:
            self.on_clip()
            self.save_state()

    def reset_clip(self):
        """Back to the default limits: Percentile 0–100 % (data min to max)."""
        _set_quiet(self.pctLo, 0.0)
        _set_quiet(self.pctHi, 100.0)
        _set_quiet(self.clipMode, 'pct')
        self.on_clip_mode(fill=False)

    def on_clip(self, *_):
        """Clip limits changed: rebuild an unedited preset, or stretch an edited curve to fit."""
        if self.sample is None or self._loading or len(self.curve.nodes) < 2:
            return
        if (self.clipMode.currentData() == 'pct' and not self.mirroring()
                and self.pctHi.value() <= self.pctLo.value()):
            return                              # wait until upper > lower
        lo, hi = self.clip_range()
        if self.clipMode.currentData() == 'pct' or self.mirroring():
            _set_quiet(self.clipLo, lo)
            _set_quiet(self.clipHi, hi)
        if self.mirroring():
            _set_quiet(self.widthSpin, (hi - lo) / 2.0)
        if self.edited:
            nodes = stretch.rescale(self.curve.nodes, lo, hi)
            if self.mirroring():
                nodes = stretch.mirror(nodes, self.centre.value(), 'pos') or nodes
        else:
            nodes = self._run_preset(self.last_preset)
        self.curve.set_nodes(nodes)
        self.follow_curve()
        self.commit()

    # ================================================================ mirror about centre
    def update_mirror_widgets(self):
        on = self.chkMirror.isChecked()
        for wdg in (self.lblWidth, self.widthSpin, self.lblSlope, self.slope):
            wdg.setEnabled(on)
        if on and self.sample is not None:
            lo, hi = self.clip_range()
            _set_quiet(self.widthSpin, (hi - lo) / 2.0)

    def on_mirror(self, on):
        self.curve.set_mirror(self.centre.value() if on else None)
        self.update_mirror_widgets()
        for wdg in (self.pctLo, self.lblPLo):
            wdg.setEnabled(self.clipMode.currentData() == 'pct' and not on)
        self._centre_prev = self.centre.value()
        if self._loading or self.sample is None or len(self.curve.nodes) < 2:
            return
        if not on:
            self.save_state()
            return
        nodes = stretch.mirror(self.curve.nodes, self.centre.value(), 'pos') if self.edited else None
        self.curve.set_nodes(nodes or self._run_preset(self.last_preset))
        lo, hi = self.clip_range()
        _set_quiet(self.clipLo, lo)
        _set_quiet(self.clipHi, hi)
        self.follow_curve()
        self.commit()

    def centre_on_median(self):
        if self.sample is not None:
            self.centre.setValue(float(np.median(self.sample)))

    def on_centre(self, c):
        old, self._centre_prev = self._centre_prev, c
        if not self.mirroring() or self._loading:
            self.save_state()
            return
        self.curve.set_mirror(c)
        nodes = None
        if self.edited:                         # move the hand-edited curve with its centre
            nodes = stretch.mirror([[x - old + c, y] for x, y in self.curve.nodes], c, 'pos')
        lo, hi = self.clip_range()
        _set_quiet(self.clipLo, lo)
        _set_quiet(self.clipHi, hi)
        _set_quiet(self.widthSpin, (hi - lo) / 2.0)
        self.curve.set_nodes(nodes or self._run_preset(self.last_preset))
        self.follow_curve()
        self.commit()

    def on_width(self, r):
        """Width ± edits the clip limits directly (switching them to Values)."""
        if not self.mirroring() or self._loading or not r > 0:
            return
        c = self.centre.value()
        _set_quiet(self.clipMode, 'val')
        _set_quiet(self.clipLo, c - r)
        _set_quiet(self.clipHi, c + r)
        self.on_clip_mode(fill=False)

    def on_slope(self, s):
        old, self._slope_prev = self._slope_prev, s
        if not self.mirroring() or self._loading or len(self.curve.nodes) < 2:
            self.save_state()
            return
        nodes = None
        if self.edited:
            nodes = stretch.mirror(stretch.reslope(self.curve.nodes, old / s), self.centre.value(), 'pos')
        self.curve.set_nodes(nodes or self._run_preset(self.last_preset))
        self.commit()

    # ================================================================ presets and points
    def _run_preset(self, kind, n=None):
        lo, hi = self.clip_range()
        n = n or self.preset_points.get(kind, DEFAULT_POINTS[kind])
        if self.mirroring():
            nodes = stretch.symmetric_preset(kind, self.sample, self.centre.value(), (hi - lo) / 2.0, n)
            s = self.slope.value()
            return stretch.reslope(nodes, 1.0 / s) if s != 1.0 else nodes
        return stretch.PRESETS[kind](self.sample, lo, hi, n)

    def preset(self, kind):
        if self.sample is None:
            return
        self.last_preset, self.edited = kind, False
        self.curve.set_nodes(self._run_preset(kind))
        self.commit()

    def sync_points(self):
        _set_quiet(self.points, len(self.curve.nodes) or 2)

    def on_points(self, n):
        nodes_now = self.curve.nodes
        if self.sample is None or len(nodes_now) < 2 or n == len(nodes_now):
            return
        if self.mirroring() and n % 2 == 0:     # mirrored curves have an odd count: step by two
            n = max(3, n - 1 if n < len(nodes_now) else n + 1)
            if n == len(nodes_now):
                self.sync_points()
                return
        if self.edited and self.mirroring():
            c = self.centre.value()
            half = [[x, y] for x, y in nodes_now if x >= c]
            nodes = stretch.mirror(stretch.resample(half, (n + 1) // 2), c, 'pos') or nodes_now
        elif self.edited:
            nodes = stretch.resample(nodes_now, n)
        else:
            self.preset_points[self.last_preset] = n
            nodes = self._run_preset(self.last_preset, n)
        self.curve.set_nodes(nodes)
        self.commit(sync=False)
        if len(nodes) != n:                     # e.g. hist-equalise merged duplicate quantiles
            self.sync_points()

    # ================================================================ curve edits
    def on_curve_changed(self):
        self.sync_points()
        if self.chkLive.isChecked() and not self._loading:
            self.timer.start()

    def on_user_edit(self):
        self.edited = True
        self.commit()

    def on_selection(self, i):
        self.nodeBox.setEnabled(i >= 0)
        if i >= 0:
            x, y = self.curve.nodes[i]
            _set_quiet(self.spinVal, x)
            _set_quiet(self.spinOut, y * 100)

    def on_spin(self, *_):
        i = self.curve.sel
        if i >= 0:
            self.curve.set_node(i, self.spinVal.value(), self.spinOut.value() / 100.0)
            self.on_selection(i)

    def on_ramp(self):
        self.update_lut()
        if self._loading:                      # ramp restored while opening a grid: don't restyle
            return
        self.save_state()
        self.apply()

    def update_lut(self):
        self.lut_q, self.lut_rgba = styling.colour_lut(self.rampBtn.colorRamp())
        self.curve.set_lut(self.lut_q[::4])

    # ================================================================ undo / redo
    def _snapshot(self):
        return {'nodes': copy.deepcopy(self.curve.nodes), 'preset': self.last_preset, 'edited': self.edited}

    def reset_history(self):
        self.history = [self._snapshot()] if len(self.curve.nodes) >= 2 else []
        self.hpos = len(self.history) - 1
        self.update_undo_buttons()

    def commit(self, sync=True):
        """Record the current curve for undo, then save and apply it."""
        if sync:
            self.sync_points()
        if len(self.curve.nodes) >= 2:
            snap = self._snapshot()
            if 0 <= self.hpos < len(self.history) and self.history[self.hpos]['nodes'] == snap['nodes']:
                self.history[self.hpos] = snap
            else:
                del self.history[self.hpos + 1:]
                self.history.append(snap)
                if len(self.history) > HISTORY_MAX:
                    self.history.pop(0)
                self.hpos = len(self.history) - 1
        self.update_undo_buttons()
        self.save_state()
        self.apply()

    def _restore(self, snap):
        self.last_preset, self.edited = snap['preset'], snap['edited']
        self.curve.set_nodes(copy.deepcopy(snap['nodes']))
        self.sync_points()
        self.update_undo_buttons()
        self.save_state()
        self.apply()

    def undo(self):
        if self.hpos > 0:
            self.hpos -= 1
            self._restore(self.history[self.hpos])

    def redo(self):
        if self.hpos < len(self.history) - 1:
            self.hpos += 1
            self._restore(self.history[self.hpos])

    def update_undo_buttons(self):
        self.btnUndo.setEnabled(self.hpos > 0)
        self.btnRedo.setEnabled(0 <= self.hpos < len(self.history) - 1)

    # ================================================================ styling and saved state
    def apply(self):
        """Style the layer with the current curve and colour ramp."""
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        styling.apply_stretch(self.layer, self.bandCombo.currentBand(), self.curve.nodes,
                              self.lut_q, self.rampBtn.colorRamp())

    def save_state(self):
        if self.layer is None or self._loading or len(self.curve.nodes) < 2:
            return
        ramp = self.rampBtn.colorRamp()
        state.save(self.layer, {
            'band': self.bandCombo.currentBand(),
            'nodes': self.curve.nodes,
            'preset': self.last_preset,
            'edited': self.edited,
            'preset_points': self.preset_points,
            'clip': {'mode': self.clipMode.currentData(),
                     'lower': self.pctLo.value(), 'upper': self.pctHi.value(),
                     'lo': self.clipLo.value(), 'hi': self.clipHi.value()},
            'view': [self.curve.lo, self.curve.hi],
            'view_mode': self.view_mode,
            'display': {'log_counts': self.chkLogHist.isChecked(), 'log_x': self.chkLogX.isChecked()},
            'mirror': {'on': self.chkMirror.isChecked(), 'centre': self.centre.value(),
                       'slope': self.slope.value()},
            'ramp': styling.ramp_to_dict(ramp) if ramp else {},
        })

    # ================================================================ files
    def _default_name(self, suffix):
        """Suggested output path next to the grid: <grid>_stretch<suffix>."""
        src = self.layer.source().split('|')[0]
        base = (os.path.splitext(src)[0] if os.path.exists(src)
                else os.path.join(os.path.expanduser('~'), self.layer.name()))
        return base + '_stretch' + suffix

    def save_style(self):
        if self.layer is None:
            return
        self.apply()
        self.save_state()
        path, _ = QFileDialog.getSaveFileName(self, 'Save style', self._default_name('.qml'), 'QGIS style (*.qml)')
        if path:
            msg, ok = self.layer.saveNamedStyle(path)
            if not ok:
                QMessageBox.warning(self, TITLE, msg)

    def _nodes_copy(self):
        return [list(n) for n in self.curve.nodes]

    def export_colourbar(self):
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        dlg = ColourBarDialog(self.layer.name(), self._nodes_copy(), self.lut_q, parent=self)
        if not dlg.exec():
            return
        s = dlg.settings()
        ext = '.' + s['fmt']
        path, _ = QFileDialog.getSaveFileName(self, 'Save colour bar', self._default_name('_colourbar' + ext),
                                              f"{s['fmt'].upper()} (*{ext})")
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        try:
            legend.save(path, s, dlg.bar_title(), self._nodes_copy(), self.lut_q)
        except Exception as e:
            QMessageBox.warning(self, TITLE, f'Could not save the colour bar:\n{e}')
            return
        self.iface.messageBar().pushSuccess(TITLE, f'Saved colour bar {os.path.basename(path)}')

    def colourbar_settings_dialog(self, parent):
        """Edit the remembered colour bar settings (opened from the image export dialog)."""
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        ColourBarDialog(self.layer.name(), self._nodes_copy(), self.lut_q,
                        settings_only=True, parent=parent).exec()

    def export_image(self):
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        lyr, prov, band = self.layer, self.layer.dataProvider(), self.bandCombo.currentBand()
        ext = lyr.extent()
        dlg = ExportDialog(lyr.width(), lyr.height(), ext.width(), ext.height(), layers.map_units(lyr), self,
                           colourbar_cb=self.colourbar_settings_dialog)
        if not dlg.exec():
            return
        s = dlg.settings()
        fmt = export.FORMATS[s['format']]
        out, _ = QFileDialog.getSaveFileName(self, 'Export image', self._default_name(fmt['ext']),
                                             f"{fmt['label']} (*{fmt['ext']})")
        if not out:
            return
        if not out.lower().endswith(fmt['ext']):
            out += fmt['ext']

        ow, oh, px, py = export.compute_grid(s, lyr.width(), lyr.height(), ext.width(), ext.height())
        x0, y1 = ext.xMinimum(), ext.yMaximum()
        geotransform = (x0, px, 0, y1, 0, -py)

        def read_strip(r0, n):
            sub = QgsRectangle(x0, y1 - (r0 + n) * py, x0 + ow * px, y1 - r0 * py)
            return layers.read_block(prov, band, sub, ow, n)

        prog = QProgressDialog('Rendering…', 'Cancel', 0, 1000, self)
        prog.setWindowModality(E(Qt, 'WindowModality.WindowModal'))
        prog.setMinimumDuration(300)

        def progress(frac, msg):
            prog.setLabelText(msg)
            prog.setValue(int(frac * 1000))
            QApplication.processEvents()
            return not prog.wasCanceled()

        native = (ow, oh) == (lyr.width(), lyr.height())
        restore, resampled = layers.provider_resampling(prov, 'nearest' if native else s['resampling'])
        try:
            ok = export.run_export(read_strip, ow, oh, geotransform, lyr.crs().toWkt(),
                                   self._nodes_copy(), self.lut_rgba, s, out, progress)
        except Exception as e:
            prog.close()
            QMessageBox.warning(self, TITLE, f'Export failed:\n{e}\n\nTry a different format or compression.')
            return
        finally:
            restore()
        prog.close()
        if not ok:
            return

        msg = f'Exported {os.path.basename(out)} ({os.path.getsize(out) / 1e6:,.1f} MB, {ow:,} × {oh:,} px)'
        if s.get('colourbar'):
            bar_settings = colourbar_settings()
            bar_path = os.path.splitext(out)[0] + '_colourbar.' + bar_settings['fmt']
            try:
                legend.save(bar_path, bar_settings, lyr.name(), self._nodes_copy(), self.lut_q)
                msg += f' + {os.path.basename(bar_path)}'
            except Exception as e:
                msg += f' (colour bar failed: {e})'
        if not native and not resampled:
            msg += " — this layer's provider can't resample, so nearest neighbour was used"
        self.iface.messageBar().pushSuccess(TITLE, msg)
        if s['add_to_map']:
            self.iface.addRasterLayer(out, os.path.splitext(os.path.basename(out))[0])
