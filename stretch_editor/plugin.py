# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""QGIS plugin entry: toolbar button and Raster menu items (show the panel, load sample data)."""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction  # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # Qt5

from .compat import E, first_attr

NAME = 'Stretch Editor'
HERE = os.path.dirname(__file__)
SAMPLE_GROUP = 'Stretch Editor sample data'
SAMPLES = [('tmi_nT.tif', 'Sample TMI (nT)'),
           ('tmi_1vd.tif', 'Sample TMI 1VD (nT/m)'),
           ('potassium_pct.tif', 'Sample potassium (%)')]


class StretchEditorPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None
        self.sample_action = None

    def initGui(self):
        icon = QIcon(os.path.join(HERE, 'icon.png'))
        self.action = QAction(icon, NAME, self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(NAME, self.action)
        self.sample_action = QAction('Load sample data', self.iface.mainWindow())
        self.sample_action.setToolTip('Add three small synthetic grids (TMI, 1VD, potassium) to try the editor')
        self.sample_action.triggered.connect(self.load_sample_data)
        self.iface.addPluginToRasterMenu(NAME, self.sample_action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginRasterMenu(NAME, self.action)
        self.iface.removePluginRasterMenu(NAME, self.sample_action)
        if self.dock:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def toggle(self, checked):
        if self.dock is None:
            from .ui.dock import StretchDock  # imported on first use to keep QGIS start-up fast
            self.dock = StretchDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(E(Qt, 'DockWidgetArea.RightDockWidgetArea'), self.dock)
            self.dock.visibilityChanged.connect(self.action.setChecked)
        self.dock.setVisible(checked)

    def load_sample_data(self):
        """Add the bundled synthetic grids in a group, zoom to them and open the editor."""
        from qgis.core import Qgis, QgsProject, QgsRasterLayer

        project = QgsProject.instance()
        group = project.layerTreeRoot().insertGroup(0, SAMPLE_GROUP)
        added, failed = [], []
        for filename, title in SAMPLES:
            layer = QgsRasterLayer(os.path.join(HERE, 'sample_data', filename), title)
            if not layer.isValid():
                failed.append(filename)
                continue
            project.addMapLayer(layer, False)
            node = group.addLayer(layer)
            node.setItemVisibilityChecked(not added)      # only the first grid starts visible
            added.append(layer)
        if failed:
            warning = first_attr((Qgis, 'MessageLevel.Warning'), (Qgis, 'Warning'))
            self.iface.messageBar().pushMessage(NAME, 'Could not load: ' + ', '.join(failed), level=warning)
        if not added:
            project.layerTreeRoot().removeChildNode(group)
            return
        self.iface.setActiveLayer(added[0])
        self.iface.zoomToActiveLayer()
        self.action.setChecked(True)
        self.toggle(True)
