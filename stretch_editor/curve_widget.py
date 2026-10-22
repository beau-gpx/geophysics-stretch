"""Interactive histogram + transfer-curve editor (ER Mapper style).

Left-click empty space        -> add a node (and drag it)
Left-drag a node              -> move it (drop it onto a neighbour to merge)
Right-click a node / Delete   -> remove it (minimum two nodes)
Mouse wheel                   -> zoom the x-axis around the cursor
Middle-drag or Shift+drag     -> pan the x-axis
Ctrl+Z / Ctrl+Y               -> undo / redo (while the curve has focus)
"""
import numpy as np

try:
    from qgis.PyQt.QtCore import Qt, pyqtSignal, QPointF, QRectF, QEvent
    from qgis.PyQt.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QPolygonF
    from qgis.PyQt.QtWidgets import QWidget, QSizePolicy
except ImportError:  # allows testing outside QGIS
    from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF, QEvent
    from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QPolygonF
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
    curveChanged = pyqtSignal()           # fires continuously while dragging
    curveEdited = pyqtSignal()            # fires when an edit is finished
    selectionChanged = pyqtSignal(int)
    viewChanged = pyqtSignal(float, float)  # user zoomed/panned the x-axis
    undoRequested = pyqtSignal()
    redoRequested = pyqtSignal()

    HIT = 8          # px: grab radius for a node
    MERGE = 7        # px: drop a node this close to a neighbour to merge them
    STRIP_H = 12     # colour strip under the x-axis
    YSTRIP_W = 12    # colour strip up the y-axis
    BINS = 256

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(E(QSizePolicy, 'Policy.Expanding'), E(QSizePolicy, 'Policy.Expanding'))
        self.setMouseTracking(True)
        self.setFocusPolicy(E(Qt, 'FocusPolicy.StrongFocus'))
        self.nodes = []
        self.sample = None
        self.counts = None
        self.lo, self.hi = 0.0, 1.0
        self.lut = None            # list of QColor
        self.log_hist = False
        self.axis = stretch.LinearAxis()
        self.sel = -1
        self.drag = -1
        self.merge_with = -1
        self.pan = None            # (start_px, t_lo, t_hi) while panning (axis space)
        self.hover = ''

    # ---------- data ----------
    def set_sample(self, sample):
        self.sample = sample
        if self.axis.log:
            self.axis = stretch.LogAxis(sample) if sample is not None and sample.size else stretch.LinearAxis()
        self._recount()
        self.update()

    def set_xlog(self, on):
        """Show the x-axis (data values) on a log scale."""
        if on and self.sample is not None and self.sample.size:
            self.axis = stretch.LogAxis(self.sample)
        else:
            self.axis = stretch.LinearAxis()
        self.set_view(self.lo, self.hi)

    def set_view(self, lo, hi):
        lo, hi = float(lo), float(hi)
        if hi < lo:
            lo, hi = hi, lo
        if not hi > lo:
            hi = lo + max(abs(lo) * 1e-6, 1e-9)
        self.lo, self.hi = self.axis.clamp(lo, hi)
        self._recount()
        self.update()

    def _t(self, v):
        return float(self.axis.fwd(v))

    def _recount(self):
        if self.sample is None or self.sample.size == 0:
            self.counts = None
            return
        edges = self.axis.inv(np.linspace(self._t(self.lo), self._t(self.hi), self.BINS + 1))
        edges = np.maximum.accumulate(edges)
        if np.all(np.diff(edges) > 0):
            self.counts, _ = np.histogram(self.sample, bins=edges)
        else:
            self.counts, _ = np.histogram(self.sample, bins=self.BINS, range=(self.lo, self.hi))

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
            self.nodes[i][0] = self._clamp_x(i, x)
        if y is not None:
            self.nodes[i][1] = min(1.0, max(0.0, y))
        self.update()
        self.curveChanged.emit()
        self.curveEdited.emit()

    def delete_node(self, i):
        if 0 <= i < len(self.nodes) and len(self.nodes) > 2:
            del self.nodes[i]
            self.sel = -1
            self.selectionChanged.emit(-1)
            self.update()
            self.curveChanged.emit()
            self.curveEdited.emit()

    # ---------- geometry ----------
    def _plot(self):
        r = self.rect()
        left = 8 + self.YSTRIP_W + 4
        return QRectF(left, 8, r.width() - left - 8, r.height() - 16 - self.STRIP_H - 18)

    def _v2px(self, v, pr):
        t0, t1 = self._t(self.lo), self._t(self.hi)
        return pr.left() + (self._t(v) - t0) / (t1 - t0) * pr.width()

    def _px2v(self, px, pr):
        t0, t1 = self._t(self.lo), self._t(self.hi)
        return float(self.axis.inv(t0 + (px - pr.left()) / pr.width() * (t1 - t0)))

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

    def _node_px(self, i, pr):
        x, y = self.nodes[i]
        return self._v2px(x, pr), self._y2py(y, pr)

    def _hit(self, mx, my):
        pr = self._plot()
        best, bd = -1, self.HIT
        for i in range(len(self.nodes)):
            px, py = self._node_px(i, pr)
            d = np.hypot(px - mx, py - my)
            if d <= bd:
                best, bd = i, d
        return best

    def _merge_candidate(self, i):
        """Neighbour of node i that is within MERGE px, or -1."""
        if len(self.nodes) <= 2:
            return -1
        pr = self._plot()
        px, py = self._node_px(i, pr)
        best, bd = -1, self.MERGE
        for j in (i - 1, i + 1):
            if 0 <= j < len(self.nodes):
                qx, qy = self._node_px(j, pr)
                d = np.hypot(px - qx, py - qy)
                if d <= bd:
                    best, bd = j, d
        return best

    # ---------- painting ----------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(E(QPainter, 'RenderHint.Antialiasing'), True)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        pr = self._plot()
        if pr.width() < 20 or pr.height() < 20:
            p.end()
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

        # colour stretch up the y-axis (output 0 at the bottom, 1 at the top)
        if self.lut:
            nl = len(self.lut)
            sx = pr.left() - 4 - self.YSTRIP_W
            hgt = int(pr.height())
            for k in range(hgt + 1):
                p.setPen(QPen(self.lut[int(round(k / max(hgt, 1) * (nl - 1)))], 1))
                y = pr.bottom() - k
                p.drawLine(QPointF(sx, y), QPointF(sx + self.YSTRIP_W, y))
            p.setPen(QPen(grid, 1))
            p.setBrush(E(Qt, 'BrushStyle.NoBrush'))
            p.drawRect(QRectF(sx, pr.top(), self.YSTRIP_W, pr.height()))

        # histogram
        if self.counts is not None and len(self.counts):
            c = self.counts.astype(float)
            if self.log_hist:
                c = np.log1p(c)
            m = c.max() if c.max() > 0 else 1.0
            bw = pr.width() / len(c)
            hc = QColor(txt)
            hc.setAlpha(70)
            p.setPen(E(Qt, 'PenStyle.NoPen'))
            p.setBrush(QBrush(hc))
            for i, v in enumerate(c):
                h = v / m * pr.height()
                if h > 0:
                    p.drawRect(QRectF(pr.left() + i * bw, pr.bottom() - h, bw + 0.5, h))

        if len(self.nodes) >= 2:
            w = int(pr.width())
            t0, t1 = self._t(self.lo), self._t(self.hi)
            xs = self.axis.inv(t0 + (np.arange(w + 1) / max(w, 1)) * (t1 - t0))
            ys = stretch.evaluate(self.nodes, xs)

            # curve
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
            if self.lut:
                sy = pr.bottom() + 4
                nl = len(self.lut)
                for k in range(w + 1):
                    p.setPen(QPen(self.lut[int(round(ys[k] * (nl - 1)))], 1))
                    p.drawLine(QPointF(pr.left() + k, sy), QPointF(pr.left() + k, sy + self.STRIP_H))

            # nodes (off-screen ones get an edge marker)
            for i in range(len(self.nodes)):
                px, py = self._node_px(i, pr)
                if px < pr.left() - 1 or px > pr.right() + 1:
                    left = px < pr.left()
                    ex = pr.left() + 1 if left else pr.right() - 1
                    d = 7 if left else -7
                    tri = QPolygonF([QPointF(ex, py), QPointF(ex + d, py - 5), QPointF(ex + d, py + 5)])
                    p.setPen(QPen(QColor(30, 30, 30), 1))
                    p.setBrush(QBrush(QColor(255, 160, 0)))
                    p.drawPolygon(tri)
                    continue
                if i == self.merge_with:
                    p.setPen(QPen(QColor(200, 0, 0), 2))
                    p.setBrush(E(Qt, 'BrushStyle.NoBrush'))
                    p.drawEllipse(QPointF(px, py), 8, 8)
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
    def _shift(self, ev):
        return bool(ev.modifiers() & E(Qt, 'KeyboardModifier.ShiftModifier'))

    def mousePressEvent(self, ev):
        mx, my = _pos(ev)
        btn = ev.button()
        if btn == E(Qt, 'MouseButton.MiddleButton') or (btn == E(Qt, 'MouseButton.LeftButton') and self._shift(ev)):
            self.pan = (mx, self._t(self.lo), self._t(self.hi))
            self.setCursor(E(Qt, 'CursorShape.ClosedHandCursor'))
            return
        if not self.nodes:
            return
        pr = self._plot()
        i = self._hit(mx, my)
        if btn == E(Qt, 'MouseButton.RightButton'):
            if i >= 0:
                self.delete_node(i)
            return
        if btn != E(Qt, 'MouseButton.LeftButton'):
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
        if self.pan:
            x0, t0, t1 = self.pan
            dt = (mx - x0) / pr.width() * (t1 - t0)
            self.set_view(float(self.axis.inv(t0 - dt)), float(self.axis.inv(t1 - dt)))
            self.viewChanged.emit(self.lo, self.hi)
            return
        if self.drag >= 0:
            v = self._clamp_x(self.drag, self._px2v(mx, pr))
            self.nodes[self.drag] = [v, self._py2y(my, pr)]
            self.merge_with = self._merge_candidate(self.drag)
            tip = '   release to merge' if self.merge_with >= 0 else ''
            self.hover = f"value {fmt(v)}   output {self.nodes[self.drag][1] * 100:.1f}%{tip}"
            self.selectionChanged.emit(self.drag)
            self.update()
            self.curveChanged.emit()
        elif pr.contains(QPointF(mx, my)):
            v = self._px2v(mx, pr)
            out = stretch.evaluate(self.nodes, [v])[0] * 100 if len(self.nodes) >= 2 else 0
            self.hover = f"value {fmt(v)}   output {out:.1f}%"
            self.update()

    def mouseReleaseEvent(self, _ev):
        if self.pan:
            self.pan = None
            self.unsetCursor()
            return
        if self.drag >= 0:
            i, j = self.drag, self._merge_candidate(self.drag)
            self.drag = self.merge_with = -1
            if j >= 0:                       # merge: keep the dragged node, drop its neighbour
                del self.nodes[j]
                self.sel = i - 1 if j < i else i
                self.selectionChanged.emit(self.sel)
                self.update()
                self.curveChanged.emit()
            self.curveEdited.emit()

    def wheelEvent(self, ev):
        d = ev.angleDelta().y()
        if not d:
            return
        pr = self._plot()
        mx, _ = _pos(ev)
        ta = self._t(self._px2v(min(max(mx, pr.left()), pr.right()), pr))
        t0, t1 = self._t(self.lo), self._t(self.hi)
        f = 0.85 ** (d / 120.0)
        self.set_view(float(self.axis.inv(ta - (ta - t0) * f)), float(self.axis.inv(ta + (t1 - ta) * f)))
        self.viewChanged.emit(self.lo, self.hi)
        ev.accept()

    def leaveEvent(self, _ev):
        self.hover = ''
        self.update()

    # ---------- keyboard ----------
    def _key_action(self, ev):
        ctrl = bool(ev.modifiers() & E(Qt, 'KeyboardModifier.ControlModifier'))
        k = ev.key()
        if ctrl and k == E(Qt, 'Key.Key_Z'):
            return 'redo' if self._shift(ev) else 'undo'
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
        elif act == 'delete':
            self.delete_node(self.sel)
        else:
            super().keyPressEvent(ev)
