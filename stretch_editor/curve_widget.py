"""Interactive histogram + transfer-curve editor (ER Mapper style).

Left-click empty space  -> add a node (and drag it)
Left-drag a node        -> move it
Right-click a node      -> delete it (minimum two nodes)
"""
import numpy as np

try:
    from qgis.PyQt.QtCore import Qt, pyqtSignal, QPointF, QRectF, QEvent
    from qgis.PyQt.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont
    from qgis.PyQt.QtWidgets import QWidget, QSizePolicy
except ImportError:  # allows testing outside QGIS
    from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF, QEvent
    from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont
    from PyQt5.QtWidgets import QWidget, QSizePolicy

from . import stretch


def E(obj, path):
    """Qt5/Qt6 enum compatibility: E(Qt, 'MouseButton.LeftButton')."""
    scope, name = path.split('.')
    try:
        return getattr(getattr(obj, scope), name)
    except AttributeError:
        return getattr(obj, name)


def _pos(event):
    if hasattr(event, 'position'):
        p = event.position()
        return p.x(), p.y()
    p = event.pos()
    return float(p.x()), float(p.y())


def fmt(v):
    return f"{v:.5g}"


class CurveWidget(QWidget):
    curveChanged = pyqtSignal()        # fires continuously while dragging
    curveEdited = pyqtSignal()         # fires when an edit is finished
    selectionChanged = pyqtSignal(int)
    undoRequested = pyqtSignal()
    redoRequested = pyqtSignal()

    HIT = 8
    STRIP_H = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(E(QSizePolicy, 'Policy.Expanding'), E(QSizePolicy, 'Policy.Expanding'))
        self.setMouseTracking(True)
        self.setFocusPolicy(E(Qt, 'FocusPolicy.StrongFocus'))
        self.nodes = []
        self.counts = None
        self.lo, self.hi = 0.0, 1.0
        self.lut = None            # list of QColor (256)
        self.log_hist = False
        self.sel = -1
        self.drag = -1
        self.hover = ''

    # ---------- data ----------
    def set_histogram(self, counts, lo, hi):
        self.counts = counts
        self.lo, self.hi = lo, hi
        self.update()

    def set_nodes(self, nodes):
        self.nodes = stretch.sanitize(nodes)
        self.sel = -1
        self.selectionChanged.emit(-1)
        self.update()

    def set_lut(self, colors):
        self.lut = colors
        self.update()

    def set_log_hist(self, on):
        self.log_hist = bool(on)
        self.update()

    def set_node(self, i, x=None, y=None):
        if not (0 <= i < len(self.nodes)):
            return
        if x is not None:
            x = self._clamp_x(i, x)
            self.nodes[i][0] = x
        if y is not None:
            self.nodes[i][1] = min(1.0, max(0.0, y))
        self.update()
        self.curveChanged.emit()
        self.curveEdited.emit()

    # ---------- geometry ----------
    def _plot(self):
        r = self.rect()
        return QRectF(8, 8, r.width() - 16, r.height() - 16 - self.STRIP_H - 18)

    def _v2px(self, v, pr):
        return pr.left() + (v - self.lo) / (self.hi - self.lo) * pr.width()

    def _px2v(self, px, pr):
        return self.lo + (px - pr.left()) / pr.width() * (self.hi - self.lo)

    def _y2py(self, y, pr):
        return pr.bottom() - y * pr.height()

    def _py2y(self, py, pr):
        return min(1.0, max(0.0, (pr.bottom() - py) / pr.height()))

    def _clamp_x(self, i, x):
        span = (self.hi - self.lo) * 1e-6
        if i > 0:
            x = max(x, self.nodes[i - 1][0] + span)
        if i < len(self.nodes) - 1:
            x = min(x, self.nodes[i + 1][0] - span)
        return x

    def _hit(self, mx, my):
        pr = self._plot()
        best, bd = -1, self.HIT
        for i, (x, y) in enumerate(self.nodes):
            d = np.hypot(self._v2px(x, pr) - mx, self._y2py(y, pr) - my)
            if d <= bd:
                best, bd = i, d
        return best

    # ---------- painting ----------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(E(QPainter, 'RenderHint.Antialiasing'), True)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        pr = self._plot()
        if pr.width() < 20 or pr.height() < 20:
            return
        txt = pal.text().color()
        grid = QColor(txt)
        grid.setAlpha(40)

        # grid
        p.setPen(QPen(grid, 1))
        for f in (0.25, 0.5, 0.75):
            y = pr.bottom() - f * pr.height()
            p.drawLine(QPointF(pr.left(), y), QPointF(pr.right(), y))
            x = pr.left() + f * pr.width()
            p.drawLine(QPointF(x, pr.top()), QPointF(x, pr.bottom()))
        p.drawRect(pr)

        # histogram
        if self.counts is not None and len(self.counts):
            c = self.counts.astype(float)
            if self.log_hist:
                c = np.log1p(c)
            m = c.max() if c.max() > 0 else 1.0
            n = len(c)
            bw = pr.width() / n
            hc = QColor(txt)
            hc.setAlpha(70)
            p.setPen(E(Qt, 'PenStyle.NoPen'))
            p.setBrush(QBrush(hc))
            for i, v in enumerate(c):
                h = v / m * pr.height()
                if h > 0:
                    p.drawRect(QRectF(pr.left() + i * bw, pr.bottom() - h, bw + 0.5, h))

        # curve
        if len(self.nodes) >= 2:
            w = int(pr.width())
            xs = self.lo + (np.arange(w + 1) / max(w, 1)) * (self.hi - self.lo)
            ys = stretch.evaluate(self.nodes, xs)
            path = QPainterPath()
            for k in range(len(xs)):
                pt = QPointF(pr.left() + k, self._y2py(ys[k], pr))
                if k == 0:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
            p.setBrush(E(Qt, 'BrushStyle.NoBrush'))
            p.setPen(QPen(QColor(220, 60, 30), 2))
            p.drawPath(path)

            # colour strip
            sy = pr.bottom() + 4
            if self.lut:
                nl = len(self.lut)
                for k in range(w + 1):
                    col = self.lut[int(round(ys[k] * (nl - 1)))]
                    p.setPen(QPen(col, 1))
                    p.drawLine(QPointF(pr.left() + k, sy), QPointF(pr.left() + k, sy + self.STRIP_H))

            # nodes
            for i, (x, y) in enumerate(self.nodes):
                px, py = self._v2px(x, pr), self._y2py(y, pr)
                if px < pr.left() - 4 or px > pr.right() + 4:
                    continue
                p.setPen(QPen(QColor(30, 30, 30), 1))
                p.setBrush(QBrush(QColor(255, 160, 0) if i == self.sel else QColor(255, 255, 255)))
                p.drawEllipse(QPointF(px, py), 4.5, 4.5)

        # labels
        p.setPen(txt)
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        ly = self.rect().bottom() - 3
        p.drawText(QPointF(pr.left(), ly), fmt(self.lo))
        hs = fmt(self.hi)
        p.drawText(QPointF(pr.right() - p.fontMetrics().horizontalAdvance(hs), ly), hs)
        if self.hover:
            p.drawText(QPointF(pr.left() + 4, pr.top() + 13), self.hover)
        p.end()

    # ---------- mouse ----------
    def mousePressEvent(self, ev):
        if not self.nodes:
            return
        mx, my = _pos(ev)
        pr = self._plot()
        i = self._hit(mx, my)
        if ev.button() == E(Qt, 'MouseButton.RightButton'):
            if i >= 0 and len(self.nodes) > 2:
                del self.nodes[i]
                self.sel = -1
                self.selectionChanged.emit(-1)
                self.update()
                self.curveChanged.emit()
                self.curveEdited.emit()
            return
        if ev.button() != E(Qt, 'MouseButton.LeftButton'):
            return
        if i < 0 and pr.contains(QPointF(mx, my)):
            v, y = self._px2v(mx, pr), self._py2y(my, pr)
            xs = [n[0] for n in self.nodes]
            if v in xs:
                return
            i = int(np.searchsorted(xs, v))
            self.nodes.insert(i, [v, y])
            self.curveChanged.emit()
        if i >= 0:
            self.sel = self.drag = i
            self.selectionChanged.emit(i)
            self.update()

    def mouseMoveEvent(self, ev):
        mx, my = _pos(ev)
        pr = self._plot()
        if self.drag >= 0:
            v = self._clamp_x(self.drag, self._px2v(mx, pr))
            self.nodes[self.drag] = [v, self._py2y(my, pr)]
            self.hover = f"value {fmt(v)}   output {self.nodes[self.drag][1] * 100:.1f}%"
            self.selectionChanged.emit(self.drag)
            self.update()
            self.curveChanged.emit()
        elif pr.contains(QPointF(mx, my)):
            v = self._px2v(mx, pr)
            out = stretch.evaluate(self.nodes, [v])[0] * 100 if len(self.nodes) >= 2 else 0
            self.hover = f"value {fmt(v)}   output {out:.1f}%"
            self.update()

    def mouseReleaseEvent(self, _ev):
        if self.drag >= 0:
            self.drag = -1
            self.curveEdited.emit()

    def leaveEvent(self, _ev):
        self.hover = ''
        self.update()

    # ---------- keyboard: undo/redo/delete while the curve has focus ----------
    def _key_action(self, ev):
        ctrl = bool(ev.modifiers() & E(Qt, 'KeyboardModifier.ControlModifier'))
        shift = bool(ev.modifiers() & E(Qt, 'KeyboardModifier.ShiftModifier'))
        k = ev.key()
        if ctrl and k == E(Qt, 'Key.Key_Z'):
            return 'redo' if shift else 'undo'
        if ctrl and k == E(Qt, 'Key.Key_Y'):
            return 'redo'
        if not ctrl and k in (E(Qt, 'Key.Key_Delete'), E(Qt, 'Key.Key_Backspace')) and self.sel >= 0:
            return 'delete'
        return None

    def event(self, ev):
        # claim these keys before QGIS's own shortcuts see them
        if ev.type() == E(QEvent, 'Type.ShortcutOverride') and self._key_action(ev):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        act = self._key_action(ev)
        if act == 'undo':
            self.undoRequested.emit()
        elif act == 'redo':
            self.redoRequested.emit()
        elif act == 'delete' and len(self.nodes) > 2:
            del self.nodes[self.sel]
            self.sel = -1
            self.selectionChanged.emit(-1)
            self.update()
            self.curveChanged.emit()
            self.curveEdited.emit()
        else:
            super().keyPressEvent(ev)
