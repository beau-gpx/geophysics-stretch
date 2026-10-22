# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Export settings dialog."""
import json

from qgis.core import QgsSettings
from qgis.gui import QgsColorButton
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..compat import E
from ..core import export as ex

SETTINGS_KEY = 'stretchEditor/exportSettings'

NOTES = {
    ('COG', 'WEBP', False): 'Smallest files with smooth transparent edges. Opens in QGIS, ArcGIS Pro and '
                            'anything on recent GDAL; older software (old ER Mapper, MapInfo) may not.',
    ('COG', 'WEBP', True):  'Lossless WEBP: exact pixels, roughly half the size of DEFLATE. Same '
                            'compatibility caveat as lossy WEBP.',
    ('COG', 'JPEG', False): 'Very widely readable. JPEG has no alpha, so the collar uses a 1-bit mask '
                            '(or a fill colour).',
    ('COG', 'ZSTD', True):  'Lossless and fast. Needs readers on GDAL 2.3 or later.',
    ('COG', 'DEFLATE', True): 'Lossless and readable almost everywhere.',
    ('COG', 'LZW', True):   'Lossless, for very old software. Usually larger than DEFLATE.',
    ('COG', 'NONE', True):  'Uncompressed. Largest files, fastest to read.',
    ('JP2', 'JPEG2000', False): 'Wavelet compression, the closest open relative of ECW. Target size is the '
                                'output as a % of uncompressed (10 % ≈ 1:10).',
    ('JP2', 'JPEG2000', True):  'Reversible (lossless) JPEG2000. Writing large images can be slow.',
    ('PNG', 'DEFLATE', True):   'Lossless and opens anywhere (reports, PowerPoint). Georeferenced by a '
                                'world file plus .aux.xml.',
    ('JPEG', 'JPEG', False):    'For reports and slides. No transparency; the collar is filled.',
}


class ExportDialog(QDialog):
    def __init__(self, width, height, ext_w, ext_h, units='', parent=None, colourbar_cb=None):
        super().__init__(parent)
        self.colourbar_cb = colourbar_cb
        self.setWindowTitle('Export stretched image')
        self.w, self.h = width, height
        self.ext_w, self.ext_h = ext_w, ext_h
        self.native_x, self.native_y = ext_w / width, ext_h / height
        self.units = units
        self.caps_comps, self.caps_fmts = ex.gdal_capabilities()

        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.fmt = QComboBox()
        for k, f in ex.FORMATS.items():
            self.fmt.addItem(f['label'], k)
        self._disable_items(self.fmt, lambda k: self.caps_fmts and k not in self.caps_fmts)
        form.addRow('Format', self.fmt)

        self.comp = QComboBox()
        form.addRow('Compression', self.comp)

        self.mode = QComboBox()
        self.mode.addItem('Lossy', False)
        self.mode.addItem('Lossless', True)
        form.addRow('Mode', self.mode)

        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.qualityLabel = QLabel('Quality')
        form.addRow(self.qualityLabel, self.quality)

        self.level = QSpinBox()
        self.levelLabel = QLabel('Compression level')
        form.addRow(self.levelLabel, self.level)

        self.transp = QComboBox()
        form.addRow('Transparency', self.transp)

        self.bg = QgsColorButton()
        self.bg.setAllowOpacity(False)
        self.bgLabel = QLabel('Background colour')
        form.addRow(self.bgLabel, self.bg)

        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        self.resMode = QComboBox()
        self.resMode.addItem('Cell size', 'cell')
        self.resMode.addItem('Scale', 'scale')
        self.scale = QSpinBox()
        self.scale.setRange(1, ex.MAX_SCALE)
        self.scale.setSuffix(' %')
        self.scale.setToolTip('100 % = native resolution; above 100 % = finer pixels (resampled)')
        self.cell = QDoubleSpinBox()
        self.cell.setDecimals(6)
        self.cell.setRange(1e-6, 1e9)
        self.cell.setSuffix(f' {units}' if units else '')
        self.cell.setToolTip('Output pixel size in map units. Smaller than native = finer (resampled).')
        rl.addWidget(self.resMode)
        rl.addWidget(self.scale, 1)
        rl.addWidget(self.cell, 1)
        form.addRow('Resolution', rw)
        square = abs(self.native_x - self.native_y) <= 1e-9 * self.native_x
        native = f'{self.native_x:.6g}' + ('' if square else f' × {self.native_y:.6g}')
        self.nativeLbl = QLabel(f'Native cell {native} {units}'.strip())
        self.nativeLbl.setStyleSheet('color: gray;')
        form.addRow('', self.nativeLbl)

        self.resamp = QComboBox()
        for k, label in ex.RESAMPLING.items():
            self.resamp.addItem(label, k)
        self.resampLabel = QLabel('Resampling')
        form.addRow(self.resampLabel, self.resamp)

        self.dims = QLabel()
        form.addRow('Output', self.dims)

        self.ovr = QCheckBox('Build overviews (pyramids) for fast display')
        form.addRow('', self.ovr)
        self.addMap = QCheckBox('Add the exported image to the map')
        form.addRow('', self.addMap)

        cbw = QWidget()
        cbl = QHBoxLayout(cbw)
        cbl.setContentsMargins(0, 0, 0, 0)
        self.chkBar = QCheckBox('Also save a colour bar')
        self.chkBar.setToolTip('Saved next to the image as <name>_colourbar.png/.svg/.pdf')
        self.btnBar = QPushButton('Settings…')
        self.btnBar.clicked.connect(lambda: self.colourbar_cb and self.colourbar_cb(self))
        self.btnBar.setEnabled(self.colourbar_cb is not None)
        cbl.addWidget(self.chkBar)
        cbl.addWidget(self.btnBar)
        cbl.addStretch()
        form.addRow('', cbw)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: gray;')
        lay.addWidget(self.note)

        bb = QDialogButtonBox(E(QDialogButtonBox, 'StandardButton.Ok') | E(QDialogButtonBox, 'StandardButton.Cancel'))
        bb.button(E(QDialogButtonBox, 'StandardButton.Ok')).setText('Export…')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._busy = False
        self.load(self._stored())
        for w in (self.fmt, self.comp, self.mode, self.transp, self.resMode, self.resamp):
            w.currentIndexChanged.connect(self.refresh)
        self.scale.valueChanged.connect(self.refresh)
        self.cell.valueChanged.connect(self.refresh)
        self.setMinimumWidth(460)

    # ------------------------------------------------ helpers
    @staticmethod
    def _disable_items(combo, pred):
        model = combo.model()
        for i in range(combo.count()):
            if pred(combo.itemData(i)) and hasattr(model, 'item'):
                model.item(i).setEnabled(False)

    @staticmethod
    def _select(combo, value):
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _stored(self):
        try:
            return json.loads(QgsSettings().value(SETTINGS_KEY, '') or '{}')
        except Exception:
            return {}

    # ------------------------------------------------ load / read
    def load(self, s):
        s = ex.normalise(s)
        self._busy = True
        self._select(self.fmt, s['format'])
        self._fill_comps(s['format'], s['compression'])
        self._select(self.mode, s['lossless'])
        self.quality.setValue(s['jp2_size'] if s['format'] == 'JP2' else s['quality'])
        self._q_store = {'q': s['quality'], 'jp2': s['jp2_size']}
        self.level.setValue(s['level'])
        self._fill_transp(s['format'], s['compression'], s['transparency'])
        self.bg.setColor(QColor(*s['bg']))
        self._select(self.resMode, 'cell')    # always open on cell size (native cell)
        self.scale.setValue(s['scale'])
        self.cell.setSingleStep(self.native_x / 10)
        self.cell.setValue(self.native_x)      # cell size always starts at this grid's native cell
        self._select(self.resamp, s['resampling'])
        self.ovr.setChecked(s['overviews'])
        self.addMap.setChecked(s['add_to_map'])
        self.chkBar.setChecked(bool(s.get('colourbar')))
        self._busy = False
        self.refresh()

    def settings(self):
        fmt, comp = self.fmt.currentData(), self.comp.currentData()
        q = self.quality.value()
        jp2 = q if fmt == 'JP2' else self._q_store['jp2']
        qq = self._q_store['q'] if fmt == 'JP2' else q
        c = self.bg.color()
        return ex.normalise(dict(
            format=fmt, compression=comp, lossless=bool(self.mode.currentData()),
            quality=qq, jp2_size=jp2, level=self.level.value(),
            transparency=self.transp.currentData(), bg=[c.red(), c.green(), c.blue()],
            res_mode=self.resMode.currentData(), scale=self.scale.value(), cell=self.cell.value(),
            resampling=self.resamp.currentData(), overviews=self.ovr.isChecked(),
            add_to_map=self.addMap.isChecked(), colourbar=self.chkBar.isChecked()))

    def accept(self):
        QgsSettings().setValue(SETTINGS_KEY, json.dumps(self.settings()))
        super().accept()

    # ------------------------------------------------ dynamic UI
    def _fill_comps(self, fmt, keep):
        self.comp.blockSignals(True)
        self.comp.clear()
        for c in ex.FORMATS[fmt]['comps']:
            self.comp.addItem(ex.COMPS[c]['label'], c)
        if fmt in ('COG', 'GTiff'):
            self._disable_items(self.comp, lambda c: self.caps_comps and c not in self.caps_comps)
        self._select(self.comp, keep)
        self.comp.blockSignals(False)

    def _fill_transp(self, fmt, comp, keep):
        self.transp.blockSignals(True)
        self.transp.clear()
        for t in ex.allowed_transparency(fmt, comp):
            self.transp.addItem(ex.TRANSP[t], t)
        self._select(self.transp, keep)
        self.transp.blockSignals(False)

    def refresh(self, *_):
        if self._busy:
            return
        self._busy = True
        fmt = self.fmt.currentData()
        prev_fmt = getattr(self, '_prev_fmt', fmt)
        if self.comp.count() == 0 or self.comp.itemData(0) != ex.FORMATS[fmt]['comps'][0]:
            self._fill_comps(fmt, self.comp.currentData())
        comp = self.comp.currentData()
        cs = ex.COMPS[comp]

        # mode
        if not cs['lossy']:
            self._select(self.mode, True)
        if not cs['lossless']:
            self._select(self.mode, False)
        self.mode.setEnabled(cs['lossy'] and cs['lossless'])
        lossless = bool(self.mode.currentData())

        # quality (JP2 uses target size %, stored separately)
        if fmt != prev_fmt and 'JP2' in (fmt, prev_fmt):
            if prev_fmt == 'JP2':
                self._q_store['jp2'] = self.quality.value()
                self.quality.setValue(self._q_store['q'])
            else:
                self._q_store['q'] = self.quality.value()
                self.quality.setValue(self._q_store['jp2'])
        self._prev_fmt = fmt
        self.qualityLabel.setText('Target size (% of raw)' if fmt == 'JP2' else 'Quality (1–100)')
        qon = cs['lossy'] and not lossless
        self.quality.setEnabled(qon)
        self.qualityLabel.setEnabled(qon)

        # level
        lv = cs['level']
        self.level.setEnabled(bool(lv))
        self.levelLabel.setEnabled(bool(lv))
        if lv:
            v = self.level.value()
            self.level.setRange(lv[0], lv[1])
            self.level.setValue(min(lv[1], max(lv[0], v)))

        # transparency
        self._fill_transp(fmt, comp, self.transp.currentData())
        none = self.transp.currentData() == 'none'
        self.bg.setEnabled(none)
        self.bgLabel.setEnabled(none)

        # overviews
        has_ovr = ex.FORMATS[fmt]['overviews']
        self.ovr.setEnabled(has_ovr)

        # dimensions / notes
        cellmode = self.resMode.currentData() == 'cell'
        self.scale.setVisible(not cellmode)
        self.cell.setVisible(cellmode)
        s = dict(res_mode=self.resMode.currentData(), scale=self.scale.value(), cell=self.cell.value())
        ow, oh, px, py = ex.compute_grid(s, self.w, self.h, self.ext_w, self.ext_h)
        native = (ow, oh) == (self.w, self.h) and abs(px - self.native_x) <= 1e-9 * self.native_x
        self.resamp.setEnabled(not native)
        self.resampLabel.setEnabled(not native)
        nb = 3 if none else 4
        raw = ow * oh * nb / 1e6
        cell_txt = f'{px:.6g}' if abs(px - py) <= 1e-9 * px else f'{px:.6g} × {py:.6g}'
        warn = '  ⚠ very large' if ow * oh > 4e8 else ''
        self.dims.setText(f'{ow:,} × {oh:,} px, cell {cell_txt} {self.units}  (raw {raw:,.1f} MB){warn}')
        note = NOTES.get((fmt if fmt != 'GTiff' else 'COG', comp, lossless), '')
        if fmt == 'GTiff':
            note += ' Plain tiled GeoTIFF: use this if a reader rejects COGs.'
        if self.caps_comps and comp not in self.caps_comps:
            note = f'{comp} is not available in this QGIS’s GDAL. ' + note
        self.note.setText(note)
        self._busy = False
