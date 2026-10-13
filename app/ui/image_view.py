import uuid

from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QTransform
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem

from app.ui.annotation_item import AnnotationItem
from app.utils.core import NAMES


class ImageView(QGraphicsView):
    objectsChanged = Signal()
    selectedObject = Signal(object)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.scene().selectionChanged.connect(self._selection)
        self.setRenderHint(self.renderHints().Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.mode = 'draw'
        self.class_id = 0
        self.objects = []
        self.items_by_id = {}
        self.size = (0, 0)
        self.start = None
        self.preview = None
        self.panning = False
        self.pan_start = None

    def load(self, path, objects):
        self.scene().clear()
        self.items_by_id.clear()
        with Image.open(path) as im:
            oriented = ImageOps.exif_transpose(im)
            w, h = oriented.size
            oriented.thumbnail((4096, 4096))
            image = oriented.convert('RGBA')
        display_w, display_h = image.size
        raw = image.tobytes()
        qimage = QImage(raw, display_w, display_h, display_w * 4, QImage.Format.Format_RGBA8888).copy()
        del image, raw
        pixmap_item = self.scene().addPixmap(QPixmap.fromImage(qimage))
        pixmap_item.setTransform(QTransform.fromScale(w / display_w, h / display_h))
        self.scene().setSceneRect(0, 0, w, h)
        self.size = (w, h)
        self.objects = objects
        for obj in self.objects:
            self.add_object(obj)
        self.fit()

    def add_object(self, obj):
        item = AnnotationItem(obj, *self.size, self.objectsChanged.emit)
        self.scene().addItem(item)
        self.items_by_id[obj['object_id']] = item

    def fit(self):
        if self.size[0]:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def actual(self):
        self.resetTransform()

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if 0.03 < self.transform().m11() * factor < 30:
            self.scale(factor, factor)

    def _point(self, event):
        p = self.mapToScene(event.position().toPoint())
        return max(0, min(p.x(), self.size[0])), max(0, min(p.y(), self.size[1]))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.panning = True
            self.pan_start = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.mode == 'draw' and event.button() == Qt.MouseButton.LeftButton and self.size[0]:
            self.start = self._point(event)
            self.preview = QGraphicsRectItem()
            self.preview.setPen(QPen(QColor('#00ffff'), 2, Qt.PenStyle.DashLine))
            self.preview.setZValue(10)
            self.scene().addItem(self.preview)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.panning:
            point = event.position().toPoint()
            delta = point - self.pan_start
            self.pan_start = point
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        if self.preview and self.start:
            x, y = self._point(event)
            x1, y1 = self.start
            self.preview.setRect(QRectF(min(x, x1), min(y, y1), abs(x - x1), abs(y - y1)))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.panning and event.button() == Qt.MouseButton.MiddleButton:
            self.panning = False
            self.viewport().unsetCursor()
            return
        if self.preview and event.button() == Qt.MouseButton.LeftButton:
            x, y = self._point(event)
            x1, y1 = self.start
            self.scene().removeItem(self.preview)
            self.preview = None
            self.start = None
            box = [min(x, x1), min(y, y1), max(x, x1), max(y, y1)]
            if box[2] - box[0] >= 2 and box[3] - box[1] >= 2:
                obj = dict(object_id=str(uuid.uuid4()), class_id=self.class_id,
                           class_name=NAMES[self.class_id], bbox=[round(v, 3) for v in box])
                self.objects.append(obj)
                self.add_object(obj)
                self.items_by_id[obj['object_id']].setSelected(True)
                self.objectsChanged.emit()
            return
        super().mouseReleaseEvent(event)

    def select_object(self, object_id):
        for oid, item in self.items_by_id.items():
            item.setSelected(oid == object_id)

    def selected_id(self):
        selected = self.scene().selectedItems()
        return selected[0].obj['object_id'] if selected and isinstance(selected[0], AnnotationItem) else None

    def _selection(self):
        self.selectedObject.emit(self.selected_id())

    def cancel(self):
        if self.preview:
            self.scene().removeItem(self.preview)
            self.preview = None
            self.start = None
        else:
            self.scene().clearSelection()
