"""Colour bar settings dialog with a live preview."""
import json

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QComboBox, QSpinBox, QLineEdit,
    QLabel, QDialogButtonBox, QScrollArea,
)
from qgis.core import QgsSettings

from . import colourbar as cb
from .curve_widget import E

SETTINGS_KEY = 'stretchEditor/colourBar'


def stored_settings():
    try:
        return cb.normalise(json.loads(QgsSettings().value(SETTINGS_KEY, '') or '{}'))
    except Exception:
        return cb.normalise({})


def store_settings(s):
    QgsSettings().setValue(SETTINGS_KEY, json.dumps(cb.normalise(s)))


class ColourBarDialog(QDialog):
    """settings_only=True: just edit the remembered settings (used from the image export)."""

    def __init__(self, title, nodes, colours, settings_only=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Colour bar settings' if settings_only else 'Export colour bar')
        self.nodes, self.colours = nodes, colours
        s = stored_settings()

        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        form = QFormLayout()
        left.addLayout(form)
        lay.addLayout(left)

        self.title = QLineEdit(title)
        form.addRow('Title', self.title)
        self.units = QLineEdit(s['units'])
        self.units.setPlaceholderText('e.g. nT, mGal, ppm')
        form.addRow('Units', self.units)

        self.orient = QComboBox()
        self.orient.addItem('Vertical', 'vertical')
        self.orient.addItem('Horizontal', 'horizontal')
        form.addRow('Orientation', self.orient)

        self.length = QSpinBox()
        self.length.setRange(100, 4000)
        self.length.setSuffix(' px')
        form.addRow('Bar length', self.length)
        self.thick = QSpinBox()
        self.thick.setRange(5, 400)
        self.thick.setSuffix(' px')
        form.addRow('Bar thickness', self.thick)

        self.ticks = QSpinBox()
        self.ticks.setRange(2, 30)
        form.addRow('Labels', self.ticks)
        self.mode = QComboBox()
        self.mode.addItem('Evenly spaced along the bar', 'colour')
        self.mode.addItem('Round numbers', 'value')
        self.mode.setToolTip('Evenly spaced suits histogram-equalised stretches;\n'
                             'round numbers suit linear stretches.')
        form.addRow('Label spacing', self.mode)
        self.dec = QSpinBox()
        self.dec.setRange(-1, 8)
        self.dec.setSpecialValueText('Auto')
        form.addRow('Decimals', self.dec)
        self.font = QSpinBox()
        self.font.setRange(6, 72)
        self.font.setSuffix(' px')
        form.addRow('Text size', self.font)

        self.bg = QComboBox()
        self.bg.addItem('Transparent', 'transparent')
        self.bg.addItem('White', 'white')
        form.addRow('Background', self.bg)
        self.fmt = QComboBox()
        self.fmt.addItem('PNG image', 'png')
        self.fmt.addItem('SVG (vector, editable)', 'svg')
        self.fmt.addItem('PDF (vector)', 'pdf')
        form.addRow('File type', self.fmt)
        self.scale = QSpinBox()
        self.scale.setRange(1, 6)
        self.scale.setSuffix(' ×')
        self.scale.setToolTip('PNG resolution multiplier (2× = 192 dpi)')
        self.scaleLbl = QLabel('PNG resolution')
        form.addRow(self.scaleLbl, self.scale)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: gray;')
        left.addWidget(self.note)

        bb = QDialogButtonBox(E(QDialogButtonBox, 'StandardButton.Ok') | E(QDialogButtonBox, 'StandardButton.Cancel'))
        bb.button(E(QDialogButtonBox, 'StandardButton.Ok')).setText('OK' if settings_only else 'Save…')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)

        self.preview = QLabel()
        self.preview.setAlignment(E(Qt, 'AlignmentFlag.AlignCenter'))
        self.preview.setStyleSheet('background: #c8c8c8;')
        area = QScrollArea()
        area.setWidget(self.preview)
        area.setWidgetResizable(True)
        area.setMinimumSize(340, 420)
        lay.addWidget(area, 1)

        self._select(self.orient, s['orientation'])
        self.length.setValue(s['length'])
        self.thick.setValue(s['thickness'])
        self.ticks.setValue(s['ticks'])
        self._select(self.mode, s['tick_mode'])
        self.dec.setValue(s['decimals'])
        self.font.setValue(s['font_px'])
        self._select(self.bg, s['background'])
        self._select(self.fmt, s['fmt'])
        self.scale.setValue(s['scale'])

        for w in (self.orient, self.mode, self.bg, self.fmt):
            w.currentIndexChanged.connect(self.refresh)
        for w in (self.length, self.thick, self.ticks, self.dec, self.font, self.scale):
            w.valueChanged.connect(self.refresh)
        self.title.textChanged.connect(self.refresh)
        self.units.textChanged.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _select(combo, value):
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def settings(self):
        return cb.normalise(dict(
            orientation=self.orient.currentData(), length=self.length.value(),
            thickness=self.thick.value(), ticks=self.ticks.value(), tick_mode=self.mode.currentData(),
            decimals=self.dec.value(), font_px=self.font.value(), units=self.units.text().strip(),
            background=self.bg.currentData(), fmt=self.fmt.currentData(), scale=self.scale.value()))

    def bar_title(self):
        return self.title.text().strip()

    def refresh(self, *_):
        s = self.settings()
        self.scale.setEnabled(s['fmt'] == 'png')
        self.scaleLbl.setEnabled(s['fmt'] == 'png')
        info = cb.bar_ticks(self.nodes, s['ticks'], s['tick_mode'])
        self.note.setText('This curve goes up and down, so labels use round numbers.'
                          if s['tick_mode'] == 'colour' and info['mode'] == 'value' else '')
        try:
            img = cb.render_image(s, self.bar_title(), self.nodes, self.colours, scale=1)
            self.preview.setPixmap(QPixmap.fromImage(img))
        except Exception as e:
            self.preview.setText(f'Preview failed: {e}')

    def accept(self):
        store_settings(self.settings())
        super().accept()
