import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction          # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction      # Qt5

from .curve_widget import E


class StretchEditorPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icon.png'))
        self.action = QAction(icon, 'Stretch Editor', self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu('Stretch Editor', self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginRasterMenu('Stretch Editor', self.action)
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def toggle(self, checked):
        if self.dock is None:
            from .dock import StretchDock
            self.dock = StretchDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(E(Qt, 'DockWidgetArea.RightDockWidgetArea'), self.dock)
            self.dock.visibilityChanged.connect(self.action.setChecked)
        self.dock.setVisible(checked)
