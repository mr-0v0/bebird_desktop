import sys
import socket
from datetime import datetime
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFile

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy,
)

ImageFile.LOAD_TRUNCATED_IMAGES = True

DEVICE_IP   = "192.168.5.1"
DEVICE_PORT = 58080
JPEG_SOI    = b'\xff\xd8'
JPEG_EOI    = b'\xff\xd9'


def parse_header(data: bytes) -> tuple[int, int, int]:
    return data[0], data[1], data[2]   # frame_id, is_last, frag_idx


def send_triggers(sock: socket.socket) -> None:
    sock.sendto(b'\x20\x37', (DEVICE_IP, DEVICE_PORT))
    sock.sendto(b'\x20\x36', (DEVICE_IP, DEVICE_PORT))


# ---------------------------------------------------------------------------
# Background streaming thread
# ---------------------------------------------------------------------------
class StreamWorker(QThread):
    frame_ready   = Signal(np.ndarray)   # RGB frame
    stats_updated = Signal(int, int)     # shown, dropped

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self) -> None:
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        send_triggers(sock)

        frame_buf = b''
        cur_fid   = -1
        cur_frag  = 0
        shown = dropped = 0

        while self._running:
            try:
                data, _ = sock.recvfrom(1500)
                if len(data) < 4:
                    continue

                fid, is_last, frag = parse_header(data)
                payload = data[4:]

                # SOI — start of a new frame
                if frag == 1 and not is_last:
                    if frame_buf:
                        dropped += 1
                    frame_buf = payload
                    cur_fid   = fid
                    cur_frag  = 1

                # EOI — final fragment
                elif is_last:
                    if not frame_buf:
                        continue
                    if fid != cur_fid:
                        frame_buf = b''
                        dropped += 1
                        continue
                    if frag != cur_frag + 1:
                        frame_buf = b''
                        dropped += 1
                        continue

                    frame_buf += payload
                    eoi_pos = frame_buf.rfind(JPEG_EOI)
                    if eoi_pos != -1:
                        frame_buf = frame_buf[:eoi_pos + 2]

                    if frame_buf[:2] == JPEG_SOI and frame_buf[-2:] == JPEG_EOI:
                        try:
                            img = Image.open(BytesIO(frame_buf))
                            img.verify()
                            img = Image.open(BytesIO(frame_buf))
                            arr = np.array(img)
                            self.frame_ready.emit(arr)
                            shown += 1
                            self.stats_updated.emit(shown, dropped)
                        except Exception:
                            dropped += 1

                    frame_buf = b''

                # MID — middle fragment
                else:
                    if not frame_buf or fid != cur_fid or frag != cur_frag + 1:
                        if frame_buf:
                            dropped += 1
                        frame_buf = b''
                        continue
                    frame_buf += payload
                    cur_frag   = frag

            except socket.timeout:
                send_triggers(sock)

        sock.close()

    def stop(self) -> None:
        self._running = False
        self.wait()


# ---------------------------------------------------------------------------
# Video display widget — fills available space, keeps aspect ratio
# ---------------------------------------------------------------------------
class VideoDisplay(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 480)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #000;")
        self._pixmap: QPixmap | None = None

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._pixmap:
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("bebird Viewer")
        self.resize(960, 720)

        self._worker: StreamWorker | None = None
        self._save_dir: Path | None = None
        self._save_frame_count = 0

        # ── Layout ──────────────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Video area
        self._display = VideoDisplay()
        root.addWidget(self._display)

        # Controls bar
        bar_widget = QWidget()
        bar_widget.setStyleSheet("background: #1a1a1a;")
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(12, 6, 12, 6)
        bar.setSpacing(8)

        style_btn  = "QPushButton { color: #fff; background: #333; border: 1px solid #555; border-radius: 4px; padding: 4px 10px; } QPushButton:hover { background: #444; } QPushButton:disabled { color: #555; }"
        style_lbl  = "color: #aaa; font-size: 12px;"
        style_info = "color: #666; font-size: 11px;"

        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setFixedWidth(100)
        self._btn_connect.setStyleSheet(style_btn)
        self._btn_connect.clicked.connect(self._toggle_stream)
        bar.addWidget(self._btn_connect)

        bar.addSpacing(12)

        self._btn_save = QPushButton("Start Saving")
        self._btn_save.setFixedWidth(110)
        self._btn_save.setStyleSheet(style_btn)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._toggle_save)
        bar.addWidget(self._btn_save)

        self._lbl_save_path = QLabel("")
        self._lbl_save_path.setStyleSheet(style_info)
        bar.addWidget(self._lbl_save_path)

        bar.addStretch()

        self._lbl_stats = QLabel("Frames: —   Dropped: —")
        self._lbl_stats.setStyleSheet(style_info)
        bar.addWidget(self._lbl_stats)

        root.addWidget(bar_widget)

    # ── Streaming ────────────────────────────────────────────────────────────

    def _toggle_stream(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker = None
            self._btn_connect.setText("Connect")
            self._btn_save.setEnabled(False)
            self._stop_saving()
            self._lbl_stats.setText("Frames: —   Dropped: —")
        else:
            self._worker = StreamWorker()
            self._worker.frame_ready.connect(self._on_frame)
            self._worker.stats_updated.connect(self._on_stats)
            self._worker.start()
            self._btn_connect.setText("Disconnect")
            self._btn_save.setEnabled(True)

    # ── Saving ───────────────────────────────────────────────────────────────

    def _toggle_save(self) -> None:
        if self._save_dir is None:
            self._save_dir = Path(datetime.now().strftime("%Y%m%d_%H%M%S"))
            self._save_dir.mkdir()
            self._save_frame_count = 0
            self._btn_save.setText("Stop Saving")
            self._lbl_save_path.setText(f"→ {self._save_dir}/")
        else:
            self._stop_saving()

    def _stop_saving(self) -> None:
        self._save_dir = None
        self._btn_save.setText("Start Saving")
        self._lbl_save_path.setText("")

    # ── Frame handling ────────────────────────────────────────────────────────

    def _on_frame(self, arr: np.ndarray) -> None:
        if self._save_dir is not None:
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            cv2.imwrite(
                str(self._save_dir / f"frame_{self._save_frame_count:05d}.png"), bgr
            )
            self._save_frame_count += 1

        h, w, ch = arr.shape
        qimg = QImage(arr.data, w, h, w * ch, QImage.Format_RGB888)
        self._display.set_pixmap(QPixmap.fromImage(qimg))

    def _on_stats(self, shown: int, dropped: int) -> None:
        self._lbl_stats.setText(f"Frames: {shown}   Dropped: {dropped}")

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.stop()
        super().closeEvent(event)


# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
