"""Dock widget: layer/band selection, curve editing, presets, undo/redo, live apply and export."""
import copy
import json
import os

import numpy as np

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QFileDialog,
    QMessageBox, QProgressDialog, QApplication, QGroupBox, QToolButton,
)
from qgis.core import (
    Qgis, QgsRasterLayer, QgsRectangle, QgsColorRampShader,
    QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsGradientColorRamp,
    QgsGradientStop, QgsMapLayerProxyModel, QgsProject,
)
from qgis.gui import QgsMapLayerComboBox, QgsRasterBandComboBox, QgsColorRampButton, QgsCollapsibleGroupBox

from . import stretch
from . import exporter
from . import colourbar
from .colourbar_dialog import ColourBarDialog, stored_settings as colourbar_settings
from .curve_widget import CurveWidget, E
from .export_dialog import ExportDialog

PROP = 'stretchEditor/state'
SAMPLE_MAX = 1200          # max sample dimension for histogram
LUT_N = 1024               # colour lookup resolution
SHADER_N = 512             # colour-ramp shader items applied to the layer
HISTORY_MAX = 200
DEFAULT_POINTS = {'linear': 32, 'histeq': 32, 'log': 32}
PRESET_NAMES = {'linear': 'Linear', 'histeq': 'Hist. equalise', 'log': 'Log-linear'}


# ---------------------------------------------------------------- helpers
def _enum(*candidates):
    for obj, path in candidates:
        try:
            cur = obj
            for part in path.split('.'):
                cur = getattr(cur, part)
            return cur
        except AttributeError:
            continue
    raise AttributeError(candidates)


def _raster_filter():
    return _enum((Qgis, 'LayerFilter.RasterLayer'), (QgsMapLayerProxyModel, 'Filter.RasterLayer'),
                 (QgsMapLayerProxyModel, 'RasterLayer'))


def _interpolated():
    return _enum((Qgis, 'ShaderInterpolationMethod.Linear'), (QgsColorRampShader, 'Type.Interpolated'),
                 (QgsColorRampShader, 'Interpolated'))


_DTYPES = [('Byte', np.uint8), ('Int8', np.int8), ('UInt16', np.uint16), ('Int16', np.int16),
           ('UInt32', np.uint32), ('Int32', np.int32), ('Float32', np.float32), ('Float64', np.float64)]


def _np_dtype(dt):
    for name, npdt in _DTYPES:
        for obj, path in ((Qgis, 'DataType.' + name), (Qgis, name)):
            try:
                if dt == _enum((obj, path)):
                    return npdt
            except AttributeError:
                pass
    raise ValueError('Unsupported raster data type (complex or unknown).')


def read_block(provider, band, extent, w, h):
    """Read a raster block as float64 with nodata -> NaN."""
    block = provider.block(band, extent, w, h)
    arr = None
    if hasattr(block, 'as_numpy'):
        try:
            a = block.as_numpy(use_masking=True)
            if np.ma.isMaskedArray(a):
                arr = a.astype(np.float64).filled(np.nan)
            else:
                arr = np.array(a, dtype=np.float64)
        except Exception:
            arr = None
    if arr is None:
        raw = bytes(block.data())
        arr = np.frombuffer(raw, dtype=_np_dtype(block.dataType())).reshape(h, w).astype(np.float64)
    if block.hasNoDataValue():
        arr[arr == block.noDataValue()] = np.nan
    if provider.sourceHasNoDataValue(band) and provider.useSourceNoDataValue(band):
        arr[arr == provider.sourceNoDataValue(band)] = np.nan
    with np.errstate(invalid='ignore'):
        arr[np.abs(arr) > 1e30] = np.nan      # float dummy values (e.g. ±3.4e38)
    return arr.reshape(h, w)


def default_ramp():
    """ER Mapper-like pseudocolour: blue -> cyan -> green -> yellow -> red -> magenta."""
    stops = [QgsGradientStop(0.2, QColor(0, 200, 255)), QgsGradientStop(0.4, QColor(0, 220, 0)),
             QgsGradientStop(0.6, QColor(255, 255, 0)), QgsGradientStop(0.8, QColor(255, 0, 0))]
    return QgsGradientColorRamp(QColor(0, 0, 255), QColor(255, 0, 255), False, stops)


def ramp_to_props(ramp):
    try:
        from qgis.core import QgsSymbolLayerUtils
        return {'variant': QgsSymbolLayerUtils.colorRampToVariant('r', ramp)}
    except Exception:
        return {'type': ramp.type(), 'props': ramp.properties()}


def ramp_from_props(d):
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


def _dspin(decimals=6):
    sb = QDoubleSpinBox()
    sb.setRange(-1e15, 1e15)
    sb.setDecimals(decimals)
    sb.setKeyboardTracking(False)
    return sb



def existing_stretch_range(layer, band):
    """(min, max) of the layer's current single-band stretch, or None."""
    try:
        r = layer.renderer()
        if r is None:
            return None
        if hasattr(r, 'contrastEnhancement') and r.contrastEnhancement() is not None:
            if hasattr(r, 'grayBand') and r.grayBand() != band:
                return None
            ce = r.contrastEnhancement()
            lo, hi = ce.minimumValue(), ce.maximumValue()
        elif hasattr(r, 'classificationMin'):
            if hasattr(r, 'band') and r.band() != band:
                return None
            lo, hi = r.classificationMin(), r.classificationMax()
        else:
            return None
        if lo is None or hi is None or not np.isfinite([lo, hi]).all() or not hi > lo:
            return None
        return float(lo), float(hi)
    except Exception:
        return None


def _map_units(layer):
    try:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.toAbbreviatedString(layer.crs().mapUnits())
    except Exception:
        return ''


def _provider_resampling(prov, method):
    """Temporarily switch the provider's resampling. Returns (restore_fn, ok)."""
    name = {'nearest': 'Nearest', 'bilinear': 'Bilinear', 'cubic': 'Cubic', 'average': 'Average'}[method]
    try:
        from qgis.core import QgsRasterDataProvider
        m = _enum((QgsRasterDataProvider, 'ResamplingMethod.' + name), (Qgis, 'RasterResamplingMethod.' + name))
        old = (prov.isProviderResamplingEnabled(), prov.zoomedInResamplingMethod(), prov.zoomedOutResamplingMethod())
    except Exception:
        return (lambda: None), method == 'nearest'

    def restore():
        try:
            prov.setZoomedInResamplingMethod(old[1])
            prov.setZoomedOutResamplingMethod(old[2])
            prov.enableProviderResampling(old[0])
        except Exception:
            pass

    try:
        ok = prov.enableProviderResampling(method != 'nearest')
        prov.setZoomedInResamplingMethod(m)
        prov.setZoomedOutResamplingMethod(m)
    except Exception:
        ok = False
    return restore, bool(ok) or method == 'nearest'


# ---------------------------------------------------------------- dock
class StretchDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__('Stretch Editor', parent)
        self.iface = iface
        self.setObjectName('StretchEditorDock')
        self.layer = None
        self.sample = None
        self._loading = False
        self.last_preset = 'linear'
        self.edited = False
        self.preset_points = dict(DEFAULT_POINTS)
        self.history, self.hpos = [], -1

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.apply)

        w = QWidget()
        lay = QVBoxLayout(w)

        # layer / band
        g = QGridLayout()
        g.addWidget(QLabel('Layer'), 0, 0)
        self.layerCombo = QgsMapLayerComboBox()
        self.layerCombo.setFilters(_raster_filter())
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

        # curve + undo/redo
        self.curve = CurveWidget()
        lay.addWidget(self.curve, 1)
        row = QHBoxLayout()
        hint = QLabel('Click add · drag move (onto a node to merge) · right-click delete · wheel zoom · Shift-drag pan')
        hint.setStyleSheet('color: gray; font-size: 8pt;')
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        self.btnUndo = QToolButton()
        self.btnUndo.setText('↶ Undo')
        self.btnUndo.setToolTip('Undo curve change (Ctrl+Z with the curve focused)')
        self.btnRedo = QToolButton()
        self.btnRedo.setText('↷ Redo')
        self.btnRedo.setToolTip('Redo curve change (Ctrl+Y / Ctrl+Shift+Z)')
        row.addWidget(self.btnUndo)
        row.addWidget(self.btnRedo)
        lay.addLayout(row)

        # view range
        row = QHBoxLayout()
        row.addWidget(QLabel('View'))
        self.viewLo = _dspin()
        self.viewHi = _dspin()
        self.viewLo.setToolTip('Left edge of the histogram (data value)')
        self.viewHi.setToolTip('Right edge of the histogram (data value)')
        row.addWidget(self.viewLo, 1)
        row.addWidget(QLabel('to'))
        row.addWidget(self.viewHi, 1)
        self.btnViewData = QToolButton()
        self.btnViewData.setText('Data')
        self.btnViewData.setToolTip('Show the full data range (min to max)')
        self.btnViewCurve = QToolButton()
        self.btnViewCurve.setText('Curve')
        self.btnViewCurve.setToolTip('Fit the view to the curve nodes')
        row.addWidget(self.btnViewData)
        row.addWidget(self.btnViewCurve)
        lay.addLayout(row)

        # presets + points
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
                                'Data with zero or negative values uses a symmetric log '
                                '(linear near zero).')
        row.addWidget(self.chkLogHist)
        row.addWidget(self.chkLogX)
        lay.addLayout(row)

        # clip limits
        box = QGroupBox('Clip limits')
        cg = QGridLayout(box)
        self.clipMode = QComboBox()
        self.clipMode.addItem('Percentile', 'pct')
        self.clipMode.addItem('Values', 'val')
        cg.addWidget(self.clipMode, 0, 0, 1, 4)
        self.pctLo = QDoubleSpinBox()
        self.pctHi = QDoubleSpinBox()
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
        self.clipLo = _dspin()
        self.clipHi = _dspin()
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
                                  'Clip limits become centre ± R (percentile mode uses the Upper %).')
        ag.addWidget(self.chkMirror, 0, 0, 1, 4)
        ag.addWidget(QLabel('Centre'), 1, 0)
        self.centre = _dspin()
        self.centre.setValue(0.0)
        ag.addWidget(self.centre, 1, 1)
        self.btnCentre0 = QToolButton()
        self.btnCentre0.setText('0')
        self.btnCentre0.setToolTip('Centre on zero')
        self.btnCentreMed = QToolButton()
        self.btnCentreMed.setText('Median')
        self.btnCentreMed.setToolTip('Centre on the data median')
        ag.addWidget(self.btnCentre0, 1, 2)
        ag.addWidget(self.btnCentreMed, 1, 3)
        lay.addWidget(adv)
        self._centre_prev = 0.0

        # selected node
        box = QGroupBox('Selected node')
        bg = QHBoxLayout(box)
        bg.addWidget(QLabel('Value'))
        self.spinVal = _dspin()
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

        # ramp + apply
        row = QHBoxLayout()
        row.addWidget(QLabel('Colour ramp'))
        self.rampBtn = QgsColorRampButton()
        self.rampBtn.setDefaultColorRamp(default_ramp())
        self.rampBtn.setColorRamp(default_ramp())
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
        row.addWidget(self.btnExport)
        row.addWidget(self.btnBar)
        row.addWidget(self.btnStyle)
        lay.addLayout(row)

        self.setWidget(w)

        # signals (Ctrl+Z / Ctrl+Y / Delete are handled by the curve while it has focus)
        self.curve.undoRequested.connect(self.undo)
        self.curve.redoRequested.connect(self.redo)
        self.curve.viewChanged.connect(self.on_curve_view)
        self.layerCombo.layerChanged.connect(self.on_layer)
        self.bandCombo.bandChanged.connect(self.on_band)
        self.btnLin.clicked.connect(lambda: self.preset('linear'))
        self.btnEq.clicked.connect(lambda: self.preset('histeq'))
        self.btnLog.clicked.connect(lambda: self.preset('log'))
        self.points.valueChanged.connect(self.on_points)
        self.chkLogHist.toggled.connect(self.on_log_hist)
        self.chkLogX.toggled.connect(self.on_log_x)
        self.viewLo.valueChanged.connect(self.on_view_spin)
        self.viewHi.valueChanged.connect(self.on_view_spin)
        self.btnViewData.clicked.connect(self.view_data)
        self.btnViewCurve.clicked.connect(self.view_curve)
        self.clipMode.currentIndexChanged.connect(self.on_clip_mode)
        self.pctLo.valueChanged.connect(self.on_clip)
        self.pctHi.valueChanged.connect(self.on_clip)
        self.clipLo.valueChanged.connect(self.on_clip)
        self.clipHi.valueChanged.connect(self.on_clip)
        self.curve.curveChanged.connect(self.on_curve_changed)
        self.curve.curveEdited.connect(self.on_user_edit)
        self.curve.selectionChanged.connect(self.on_selection)
        self.spinVal.valueChanged.connect(self.on_spin)
        self.spinOut.valueChanged.connect(self.on_spin)
        self.rampBtn.colorRampChanged.connect(self.on_ramp)
        self.btnApply.clicked.connect(self.apply)
        self.btnUndo.clicked.connect(self.undo)
        self.btnRedo.clicked.connect(self.redo)
        self.btnExport.clicked.connect(self.export_image)
        self.btnStyle.clicked.connect(self.save_style)
        self.btnBar.clicked.connect(self.export_colourbar)
        self.chkMirror.toggled.connect(self.on_mirror)
        self.centre.valueChanged.connect(self.on_centre)
        self.btnCentre0.clicked.connect(lambda: self.centre.setValue(0.0))
        self.btnCentreMed.clicked.connect(
            lambda: self.sample is not None and self.centre.setValue(float(np.median(self.sample))))
        self._syncing = False
        self.iface.currentLayerChanged.connect(self.on_active_layer)

        self.on_clip_mode()
        self.update_lut()
        self.update_undo_buttons()
        active = self.iface.activeLayer()      # open on the grid already selected in the Layers panel
        if isinstance(active, QgsRasterLayer):
            self.layerCombo.blockSignals(True)
            self.layerCombo.setLayer(active)
            self.layerCombo.blockSignals(False)
        self.on_layer(self.layerCombo.currentLayer())

    # ------------------------------------------------ loading
    def on_layer(self, layer):
        self.layer = layer if isinstance(layer, QgsRasterLayer) else None
        self.bandCombo.setLayer(self.layer)
        self.on_band(self.bandCombo.currentBand())
        if self.layer is not None and self.chkSync.isChecked():
            self.show_in_layers_panel(self.layer)

    # ------------------------------------------------ Layers panel sync
    def show_in_layers_panel(self, layer):
        """Make layer the active layer: expand its groups, select and scroll to it."""
        if self._syncing:
            return
        self._syncing = True
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            parent = node.parent() if node else None
            while parent is not None:
                if hasattr(parent, 'setExpanded'):
                    parent.setExpanded(True)
                parent = parent.parent()
            self.iface.setActiveLayer(layer)
            view = self.iface.layerTreeView()
            if view is not None:
                view.setCurrentLayer(layer)
                view.scrollTo(view.currentIndex())
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

    def cleanup(self):
        try:
            self.iface.currentLayerChanged.disconnect(self.on_active_layer)
        except Exception:
            pass

    def on_band(self, band):
        self.sample = None
        if self.layer is None or band is None or band < 1:
            self.curve.set_sample(None)
            self.curve.set_nodes([])
            self.reset_history()
            return
        try:
            prov = self.layer.dataProvider()
            w, h = self.layer.width(), self.layer.height()
            f = min(1.0, SAMPLE_MAX / max(w, h))
            sw, sh = max(1, int(w * f)), max(1, int(h * f))
            a = read_block(prov, band, self.layer.extent(), sw, sh)
            s = a[np.isfinite(a)]
            if s.size < 2:
                raise ValueError('Band has no valid data.')
            self.sample = s
        except Exception as e:
            QMessageBox.warning(self, 'Stretch Editor', f'Could not read band: {e}')
            return

        self._loading = True
        dlo, dhi = stretch.data_range(s)
        step = (dhi - dlo) / 200.0 or 1.0
        for sb in (self.clipLo, self.clipHi, self.spinVal, self.viewLo, self.viewHi, self.centre):
            sb.setSingleStep(step)
        self.curve.set_sample(s)

        state = self.load_state()
        disp = (state or {}).get('display', {})
        self._set_quiet_check(self.chkLogHist, disp.get('log_counts', self.chkLogHist.isChecked()))
        self._set_quiet_check(self.chkLogX, disp.get('log_x', self.chkLogX.isChecked()))
        self.curve.set_log_hist(self.chkLogHist.isChecked())
        self.curve.set_xlog(self.chkLogX.isChecked())
        mir = (state or {}).get('mirror', {}) if state and state.get('band') == band else {}
        self._set_quiet(self.centre, mir.get('centre', 0.0))
        self._centre_prev = self.centre.value()
        self._set_quiet_check(self.chkMirror, mir.get('on', False))
        self.curve.set_mirror(self.centre.value() if self.chkMirror.isChecked() else None)
        if state and state.get('band') == band and len(state.get('nodes', [])) >= 2:
            ramp = ramp_from_props(state.get('ramp', {}))
            if ramp:
                self.rampBtn.setColorRamp(ramp)
            self.last_preset = state.get('preset', 'linear')
            self.edited = bool(state.get('edited', True))
            self.preset_points.update(state.get('preset_points', {}))
            clip = state.get('clip', {})
            if 'lower' in clip:
                plo, phi = clip['lower'], clip['upper']
            else:                                   # v1.1 stored one symmetric percent
                p = clip.get('pct', 0.0)
                plo, phi = p, 100.0 - p
            self._set_quiet(self.pctLo, plo)
            self._set_quiet(self.pctHi, phi)
            self._set_quiet(self.clipMode, 'val' if clip.get('mode') == 'val' else 'pct')
            nodes = state['nodes']
            self._set_quiet(self.clipLo, clip.get('lo', nodes[0][0]))
            self._set_quiet(self.clipHi, clip.get('hi', nodes[-1][0]))
            self.curve.set_nodes(nodes)
            view = state.get('view') or (dlo, dhi)
        else:
            self.last_preset, self.edited = 'linear', False
            current = existing_stretch_range(self.layer, band)
            if current:
                # start from the stretch the layer already has (shown, not applied)
                lo, hi = current
                self._set_quiet(self.clipMode, 'val')
            else:
                lo, hi = stretch.percent_clip(s, self.pctLo.value(), self.pctHi.value())
            self._set_quiet(self.clipLo, lo)        # new grid: start the value limits from its data
            self._set_quiet(self.clipHi, hi)
            self.curve.set_nodes(self._run_preset('linear'))
            view = (dlo, dhi)
        self.on_clip_mode(fill=False)
        self.set_view(*view)
        self.sync_points()
        self._loading = False
        self.reset_history()
        self.update_lut()
        # Opening a grid never restyles it: the layer keeps its current stretch until you
        # edit the curve, pick a preset, change the clip or ramp, or press Apply.

    @staticmethod
    def _set_quiet_check(box, on):
        box.blockSignals(True)
        box.setChecked(bool(on))
        box.blockSignals(False)

    def on_log_hist(self, on):
        self.curve.set_log_hist(on)
        self.save_state()

    def on_log_x(self, on):
        self.curve.set_xlog(on)
        self.on_curve_view(self.curve.lo, self.curve.hi)

    @staticmethod
    def _set_quiet(widget, value):
        widget.blockSignals(True)
        if isinstance(widget, QComboBox):
            i = widget.findData(value)
            if i >= 0:
                widget.setCurrentIndex(i)
        else:
            widget.setValue(value)
        widget.blockSignals(False)

    # ------------------------------------------------ view range
    def set_view(self, lo, hi):
        self.curve.set_view(lo, hi)
        self._set_quiet(self.viewLo, self.curve.lo)
        self._set_quiet(self.viewHi, self.curve.hi)
        self.save_state()

    def on_curve_view(self, lo, hi):      # wheel / pan in the editor
        self._set_quiet(self.viewLo, lo)
        self._set_quiet(self.viewHi, hi)
        self.save_state()

    def on_view_spin(self, *_):
        if self.viewHi.value() > self.viewLo.value():
            self.set_view(self.viewLo.value(), self.viewHi.value())

    def view_data(self):
        if self.sample is not None:
            self.set_view(*stretch.data_range(self.sample))

    def view_curve(self):
        if len(self.curve.nodes) >= 2:
            self.set_view(*stretch.fit_curve_view(self.curve.nodes))

    # ------------------------------------------------ clip limits
    def mirroring(self):
        return self.chkMirror.isChecked() and self.sample is not None

    def clip_range(self):
        if self.mirroring():
            c = self.centre.value()
            if self.clipMode.currentData() == 'val':
                r = max(abs(self.clipLo.value() - c), abs(self.clipHi.value() - c)) or 1e-9
            else:
                r = stretch.mirror_radius(self.sample, c, self.pctHi.value())
            return c - r, c + r
        if self.clipMode.currentData() == 'val':
            lo, hi = self.clipLo.value(), self.clipHi.value()
            if hi < lo:
                lo, hi = hi, lo
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
            # start from what is currently applied
            self._set_quiet(self.clipLo, self.curve.nodes[0][0])
            self._set_quiet(self.clipHi, self.curve.nodes[-1][0])
        if not self._loading:
            self.on_clip()          # apply the limits of the newly chosen mode
            self.save_state()

    def on_clip(self, *_):
        if self.sample is None or self._loading or len(self.curve.nodes) < 2:
            return
        if (self.clipMode.currentData() == 'pct' and not self.mirroring()
                and self.pctHi.value() <= self.pctLo.value()):
            return                  # wait until upper > lower
        lo, hi = self.clip_range()
        if self.clipMode.currentData() == 'pct' or self.mirroring():
            self._set_quiet(self.clipLo, lo)
            self._set_quiet(self.clipHi, hi)
        if self.edited:
            nodes = stretch.rescale(self.curve.nodes, lo, hi)   # keep the hand-edited shape
            if self.mirroring():
                nodes = stretch.mirror(nodes, self.centre.value(), 'pos') or nodes
        else:
            nodes = self._run_preset(self.last_preset)
        self.curve.set_nodes(nodes)
        self.commit()

    # ------------------------------------------------ mirror about centre
    def on_mirror(self, on):
        self.curve.set_mirror(self.centre.value() if on else None)
        for wdg in (self.pctLo, self.lblPLo):
            wdg.setEnabled(self.clipMode.currentData() == 'pct' and not on)
        self._centre_prev = self.centre.value()
        if self._loading or self.sample is None or len(self.curve.nodes) < 2:
            return
        if on:
            nodes = stretch.mirror(self.curve.nodes, self.centre.value(), 'pos') if self.edited else None
            self.curve.set_nodes(nodes or self._run_preset(self.last_preset))
            lo, hi = self.clip_range()
            self._set_quiet(self.clipLo, lo)
            self._set_quiet(self.clipHi, hi)
            self.commit()
        else:
            self.save_state()

    def on_centre(self, c):
        old, self._centre_prev = self._centre_prev, c
        if not self.mirroring() or self._loading:
            self.save_state()
            return
        self.curve.set_mirror(c)
        if self.edited:          # move the hand-edited curve with its centre
            nodes = stretch.mirror([[x - old + c, y] for x, y in self.curve.nodes], c, 'pos')
        else:
            nodes = None
        lo, hi = self.clip_range()
        self._set_quiet(self.clipLo, lo)
        self._set_quiet(self.clipHi, hi)
        self.curve.set_nodes(nodes or self._run_preset(self.last_preset))
        self.commit()

    # ------------------------------------------------ presets / points
    def _run_preset(self, kind, n=None):
        lo, hi = self.clip_range()
        n = n or self.preset_points.get(kind, DEFAULT_POINTS[kind])
        if self.mirroring():
            c = self.centre.value()
            return stretch.symmetric_preset(kind, self.sample, c, (hi - lo) / 2.0, n)
        return stretch.PRESETS[kind](self.sample, lo, hi, n)

    def preset(self, kind):
        if self.sample is None:
            return
        self.last_preset, self.edited = kind, False
        self.curve.set_nodes(self._run_preset(kind))
        self.commit()

    def sync_points(self):
        self._set_quiet(self.points, len(self.curve.nodes) or 2)

    def on_points(self, n):
        if self.sample is None or len(self.curve.nodes) < 2 or n == len(self.curve.nodes):
            return
        if self.mirroring() and n % 2 == 0:       # mirrored curves have an odd count: step by two
            n = n - 1 if n < len(self.curve.nodes) else n + 1
            n = max(3, n)
            if n == len(self.curve.nodes):
                self.sync_points()
                return
        if self.edited and self.mirroring():
            c = self.centre.value()
            half = [[x, y] for x, y in self.curve.nodes if x >= c]
            nodes = stretch.mirror(stretch.resample(half, (n + 1) // 2), c, 'pos') or self.curve.nodes
        elif self.edited:
            nodes = stretch.resample(self.curve.nodes, n)
        else:
            self.preset_points[self.last_preset] = n
            nodes = self._run_preset(self.last_preset, n)
        self.curve.set_nodes(nodes)
        self.commit(sync=False)
        if len(nodes) != n:      # e.g. hist-equalise merged duplicate quantiles
            self.sync_points()

    # ------------------------------------------------ editing
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
            self._set_quiet(self.spinVal, x)
            self._set_quiet(self.spinOut, y * 100)

    def on_spin(self, *_):
        i = self.curve.sel
        if i >= 0:
            self.curve.set_node(i, self.spinVal.value(), self.spinOut.value() / 100.0)
            self.on_selection(i)

    def on_ramp(self):
        self.update_lut()
        if self._loading:          # ramp restored while opening a grid: don't restyle it
            return
        self.save_state()
        self.apply()

    def update_lut(self):
        ramp = self.rampBtn.colorRamp() or default_ramp()
        cols = [ramp.color(i / (LUT_N - 1)) for i in range(LUT_N)]
        self.lut_q = cols
        self.lut_rgba = np.array([[c.red(), c.green(), c.blue(), c.alpha()] for c in cols], dtype=np.uint8)
        self.curve.set_lut(cols[::4])

    # ------------------------------------------------ undo / redo
    def _snapshot(self):
        return {'nodes': copy.deepcopy(self.curve.nodes), 'preset': self.last_preset, 'edited': self.edited}

    def reset_history(self):
        self.history = [self._snapshot()] if len(self.curve.nodes) >= 2 else []
        self.hpos = len(self.history) - 1
        self.update_undo_buttons()

    def commit(self, sync=True):
        """Record the current curve, then save and apply it."""
        if sync:
            self.sync_points()
        if len(self.curve.nodes) >= 2:
            snap = self._snapshot()
            if not (0 <= self.hpos < len(self.history)) or self.history[self.hpos]['nodes'] != snap['nodes']:
                del self.history[self.hpos + 1:]
                self.history.append(snap)
                if len(self.history) > HISTORY_MAX:
                    self.history.pop(0)
                self.hpos = len(self.history) - 1
            else:
                self.history[self.hpos] = snap
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

    # ------------------------------------------------ apply to layer
    def apply(self):
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        band = self.bandCombo.currentBand()
        nodes = self.curve.nodes
        x0, x1 = nodes[0][0], nodes[-1][0]
        vals = np.unique(np.concatenate([np.linspace(x0, x1, SHADER_N), [n[0] for n in nodes]]))
        ts = stretch.evaluate(nodes, vals)
        items = [QgsColorRampShader.ColorRampItem(float(v), self.lut_q[int(round(t * (LUT_N - 1)))], '')
                 for v, t in zip(vals, ts)]
        sh = QgsColorRampShader()
        sh.setColorRampType(_interpolated())
        sh.setColorRampItemList(items)
        sh.setMinimumValue(x0)
        sh.setMaximumValue(x1)
        sh.setClip(False)
        try:
            ramp = self.rampBtn.colorRamp()
            if ramp:
                sh.setSourceColorRamp(ramp)
        except Exception:
            pass
        try:
            from qgis.core import QgsColorRampLegendNodeSettings
            ls = QgsColorRampLegendNodeSettings()
            ls.setUseContinuousLegend(True)
            sh.setLegendSettings(ls)
        except Exception:
            pass
        rs = QgsRasterShader()
        rs.setRasterShaderFunction(sh)
        r = QgsSingleBandPseudoColorRenderer(self.layer.dataProvider(), band, rs)
        r.setClassificationMin(x0)
        r.setClassificationMax(x1)
        self.layer.setRenderer(r)
        self.layer.triggerRepaint()
        try:
            self.layer.emitStyleChanged()
        except Exception:
            pass

    # ------------------------------------------------ state
    def save_state(self):
        if self.layer is None or self._loading or len(self.curve.nodes) < 2:
            return
        ramp = self.rampBtn.colorRamp()
        state = {'band': self.bandCombo.currentBand(), 'nodes': self.curve.nodes,
                 'preset': self.last_preset, 'edited': self.edited,
                 'preset_points': self.preset_points,
                 'clip': {'mode': self.clipMode.currentData(),
                          'lower': self.pctLo.value(), 'upper': self.pctHi.value(),
                          'lo': self.clipLo.value(), 'hi': self.clipHi.value()},
                 'view': [self.curve.lo, self.curve.hi],
                 'display': {'log_counts': self.chkLogHist.isChecked(), 'log_x': self.chkLogX.isChecked()},
                 'mirror': {'on': self.chkMirror.isChecked(), 'centre': self.centre.value()},
                 'ramp': ramp_to_props(ramp) if ramp else {}}
        try:
            self.layer.setCustomProperty(PROP, json.dumps(state))
        except TypeError:
            state['ramp'] = {}
            self.layer.setCustomProperty(PROP, json.dumps(state))

    def load_state(self):
        try:
            return json.loads(self.layer.customProperty(PROP, '') or 'null')
        except Exception:
            return None

    def save_style(self):
        if self.layer is None:
            return
        self.apply()
        self.save_state()
        path, _ = QFileDialog.getSaveFileName(self, 'Save style', self._default_name('.qml'), 'QGIS style (*.qml)')
        if path:
            msg, ok = self.layer.saveNamedStyle(path)
            if not ok:
                QMessageBox.warning(self, 'Stretch Editor', msg)

    def _default_name(self, ext):
        src = self.layer.source().split('|')[0]
        base = os.path.splitext(src)[0] if os.path.exists(src) else os.path.join(os.path.expanduser('~'), self.layer.name())
        return base + '_stretch' + ext

    # ------------------------------------------------ colour bar
    def export_colourbar(self):
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        nodes = [list(n) for n in self.curve.nodes]
        dlg = ColourBarDialog(self.layer.name(), nodes, self.lut_q, parent=self)
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
            colourbar.save(path, s, dlg.bar_title(), nodes, self.lut_q)
        except Exception as e:
            QMessageBox.warning(self, 'Stretch Editor', f'Could not save the colour bar:\n{e}')
            return
        self.iface.messageBar().pushSuccess('Stretch Editor', f'Saved colour bar {os.path.basename(path)}')

    def colourbar_settings_dialog(self, parent):
        """Edit the remembered colour bar settings (from the image export dialog)."""
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        ColourBarDialog(self.layer.name(), [list(n) for n in self.curve.nodes], self.lut_q,
                        settings_only=True, parent=parent).exec()

    # ------------------------------------------------ export
    def export_image(self):
        if self.layer is None or len(self.curve.nodes) < 2:
            return
        lyr, prov, band = self.layer, self.layer.dataProvider(), self.bandCombo.currentBand()
        ext = lyr.extent()
        dlg = ExportDialog(lyr.width(), lyr.height(), ext.width(), ext.height(), _map_units(lyr), self,
                           colourbar_cb=self.colourbar_settings_dialog)
        if not dlg.exec():
            return
        s = dlg.settings()
        fmt = exporter.FORMATS[s['format']]
        out, _ = QFileDialog.getSaveFileName(self, 'Export image', self._default_name(fmt['ext']),
                                             f"{fmt['label']} (*{fmt['ext']})")
        if not out:
            return
        if not out.lower().endswith(fmt['ext']):
            out += fmt['ext']

        ow, oh, px, py = exporter.compute_grid(s, lyr.width(), lyr.height(), ext.width(), ext.height())
        x0, y1 = ext.xMinimum(), ext.yMaximum()
        gt = (x0, px, 0, y1, 0, -py)

        def read_strip(r0, n):
            sub = QgsRectangle(x0, y1 - (r0 + n) * py, x0 + ow * px, y1 - r0 * py)
            return read_block(prov, band, sub, ow, n)

        prog = QProgressDialog('Rendering…', 'Cancel', 0, 1000, self)
        prog.setWindowModality(E(Qt, 'WindowModality.WindowModal'))
        prog.setMinimumDuration(300)

        def progress(frac, msg):
            prog.setLabelText(msg)
            prog.setValue(int(frac * 1000))
            QApplication.processEvents()
            return not prog.wasCanceled()

        native = (ow, oh) == (lyr.width(), lyr.height())
        restore, resamp_ok = _provider_resampling(prov, 'nearest' if native else s['resampling'])
        try:
            ok = exporter.run_export(read_strip, ow, oh, gt, lyr.crs().toWkt(),
                                     [list(n) for n in self.curve.nodes], self.lut_rgba, s, out, progress)
        except Exception as e:
            prog.close()
            QMessageBox.warning(self, 'Stretch Editor',
                                f'Export failed:\n{e}\n\nTry a different format or compression.')
            return
        finally:
            restore()
        prog.close()
        if not ok:
            return
        size = os.path.getsize(out) / 1e6
        msg = f'Exported {os.path.basename(out)} ({size:,.1f} MB, {ow:,} × {oh:,} px)'
        if s.get('colourbar'):
            cbs = colourbar_settings()
            bar_path = os.path.splitext(out)[0] + '_colourbar.' + cbs['fmt']
            try:
                colourbar.save(bar_path, cbs, lyr.name(), [list(n) for n in self.curve.nodes], self.lut_q)
                msg += f' + {os.path.basename(bar_path)}'
            except Exception as e:
                msg += f' (colour bar failed: {e})'
        if not native and not resamp_ok:
            msg += f" — this layer's provider can't resample, so nearest neighbour was used"
        self.iface.messageBar().pushSuccess('Stretch Editor', msg)
        if s['add_to_map']:
            self.iface.addRasterLayer(out, os.path.splitext(os.path.basename(out))[0])
