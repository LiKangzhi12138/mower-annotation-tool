from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QFont
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsSimpleTextItem

from app.utils.core import classes


class AnnotationItem(QGraphicsRectItem):
    def __init__(self, obj, width, height, changed):
        super().__init__()
        self.obj, self.width, self.height, self.changed = obj, width, height, changed
        self.mode = None
        self.start = None
        self.original = None
        self.setZValue(2)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.label = QGraphicsSimpleTextItem(self)
        self.label.setBrush(QBrush(QColor('white')))
        self.label.setFont(QFont('Microsoft YaHei', 10, QFont.Weight.Bold))
        self.refresh()

    def refresh(self):
        x1, y1, x2, y2 = self.obj['bbox']
        self.setRect(QRectF(x1, y1, x2 - x1, y2 - y1))
        category = classes()['classes'][self.obj['class_id']]
        self.setPen(QPen(QColor(self.obj.get('display_color', category['color'])), 2))
        self.label.setText(self.obj.get('display_label', category['zh']))
        self.label.setPos(x1, max(0, y1 - 22))

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            r = self.rect()
            painter.setPen(QPen(QColor('white'), 1))
            painter.setBrush(QBrush(QColor(self.pen().color())))
            for x in (r.left(), r.center().x(), r.right()):
                for y in (r.top(), r.center().y(), r.bottom()):
                    if x == r.center().x() and y == r.center().y():
                        continue
                    painter.drawRect(QRectF(x-4, y-4, 8, 8))

    def mousePressEvent(self, event):
        p, r = event.scenePos(), self.rect()
        margin = 8
        horizontal = 'l' if abs(p.x() - r.left()) < margin else ('r' if abs(p.x() - r.right()) < margin else '')
        vertical = 't' if abs(p.y() - r.top()) < margin else ('b' if abs(p.y() - r.bottom()) < margin else '')
        self.mode = horizontal + vertical or 'move'
        self.start = p
        self.original = list(self.obj['bbox'])
        self.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.mode:
            return
        x1, y1, x2, y2 = self.original
        dx, dy = event.scenePos().x() - self.start.x(), event.scenePos().y() - self.start.y()
        if self.mode == 'move':
            dx = max(-x1, min(dx, self.width - x2))
            dy = max(-y1, min(dy, self.height - y2))
            x1 += dx; x2 += dx; y1 += dy; y2 += dy
        else:
            if 'l' in self.mode: x1 = max(0, min(x1 + dx, x2 - 1))
            if 'r' in self.mode: x2 = min(self.width, max(x2 + dx, x1 + 1))
            if 't' in self.mode: y1 = max(0, min(y1 + dy, y2 - 1))
            if 'b' in self.mode: y2 = min(self.height, max(y2 + dy, y1 + 1))
        self.obj['bbox'] = [round(v, 3) for v in (x1, y1, x2, y2)]
        self.refresh()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.mode:
            self.mode = None
            self.changed()
        event.accept()
