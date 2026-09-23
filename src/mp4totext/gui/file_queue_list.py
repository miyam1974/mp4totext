from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QListWidget, QSizePolicy


class FileQueueList(QListWidget):
    """File list that doubles as the MP4 drag-and-drop target."""

    files_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setObjectName("fileList")
        self._visible_rows = 5
        self._cached_row_height: int | None = None
        self._placeholder_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder_text = text
        self.viewport().update()

    def sizeHint(self) -> QSize:
        width = super().sizeHint().width()
        return QSize(width, self._row_height() * self._visible_rows)

    def _row_height(self) -> int:
        # Measure Qt's real per-item height (includes delegate/DPI overhead
        # that a plain font-metrics estimate misses) via a throwaway item,
        # caching the result since sizeHint() can be queried very often.
        if self._cached_row_height is None:
            temporary_row = self.count()
            self.addItem("")
            height = self.sizeHintForRow(temporary_row)
            self.takeItem(temporary_row)
            self._cached_row_height = height if height > 0 else self.fontMetrics().height() + 8
        return self._cached_row_height

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._is_acceptable(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        # QAbstractItemView's own dragMoveEvent rejects drags that aren't its
        # internal item-reordering mime type, so external file drags need it
        # explicitly re-accepted here to keep dropEvent from being cancelled.
        if self._is_acceptable(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        if not self._is_acceptable(event):
            return
        sources = tuple(Path(url.toLocalFile()) for url in event.mimeData().urls())
        self.files_dropped.emit(sources)
        event.acceptProposedAction()

    @staticmethod
    def _is_acceptable(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
        urls = event.mimeData().urls()
        return bool(urls) and all(Path(url.toLocalFile()).suffix.lower() == ".mp4" for url in urls)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        viewport_rect = self.viewport().rect()
        if self.count() == 0:
            empty_top = viewport_rect.top()
        else:
            last_row_bottom = self.visualItemRect(self.item(self.count() - 1)).bottom()
            empty_top = max(last_row_bottom, viewport_rect.top())
        empty_rect = QRect(
            viewport_rect.left(),
            empty_top,
            viewport_rect.width(),
            viewport_rect.bottom() - empty_top,
        )
        if empty_rect.height() < 8:
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#526258"))
        painter.drawText(
            empty_rect,
            int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
            self._placeholder_text,
        )


