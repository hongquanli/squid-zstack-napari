"""Drag-and-drop launcher for view_stack.py.

Drop one or more Squid acquisition folders onto the window (or onto the desktop shortcut)
to open each in its own napari viewer.

Usage: pythonw launcher.py [dataset_dir ...]
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QLabel,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

HERE = Path(__file__).resolve().parent
VIEWER = HERE / "view_stack.py"
LOG_DIR = HERE / "logs"
PARAMS_FILE = "acquisition parameters.json"


def find_dataset(path: Path) -> Path | None:
    """Accept the acquisition folder itself, its '0' subfolder, or any file inside it."""
    if path.is_file():
        path = path.parent
    for candidate in (path, path.parent):
        if (candidate / PARAMS_FILE).exists():
            return candidate
    return None


class DropZone(QLabel):
    def __init__(self, on_drop):
        super().__init__("Drop acquisition folder(s) here")
        self.on_drop = on_drop
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(160)
        self.setAcceptDrops(True)
        self._set_style(False)

    def _set_style(self, hover):
        border = "#4caf50" if hover else "#888"
        self.setStyleSheet(
            f"QLabel {{ border: 2px dashed {border}; border-radius: 10px; font-size: 16px; padding: 20px; }}"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_style(True)

    def dragLeaveEvent(self, event):
        self._set_style(False)

    def dropEvent(self, event):
        self._set_style(False)
        self.on_drop([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])


class Launcher(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Squid z-stack viewer")
        self.resize(460, 420)

        self.bin = QSpinBox()
        self.bin.setRange(1, 8)
        self.bin.setValue(2)
        self.bin.setToolTip("XY binning for display (1 = full resolution, needs lots of GPU memory)")
        self.z_scale = QDoubleSpinBox()
        self.z_scale.setRange(0.1, 5.0)
        self.z_scale.setSingleStep(0.01)
        self.z_scale.setValue(1.0)
        self.z_scale.setToolTip("Multiply the stage z step (e.g. refractive-index focal-shift correction)")
        self.no_labels = QCheckBox("Start with tick numbers / axis titles hidden")

        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        form = QFormLayout()
        form.addRow("XY binning:", self.bin)
        form.addRow("Z scale:", self.z_scale)
        form.addRow(self.no_labels)

        layout = QVBoxLayout(self)
        layout.addWidget(DropZone(self.open_paths))
        layout.addWidget(browse)
        layout.addLayout(form)
        layout.addWidget(self.log)

    def browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select acquisition folder")
        if folder:
            self.open_paths([Path(folder)])

    def open_paths(self, paths):
        for path in paths:
            dataset = find_dataset(path)
            if dataset is None:
                self.log.appendPlainText(f"✗ {path.name}: no '{PARAMS_FILE}' found")
                continue
            self.launch(dataset)

    def launch(self, dataset: Path):
        cmd = [sys.executable, str(VIEWER), str(dataset), "--bin", str(self.bin.value()),
               "--z-scale", f"{self.z_scale.value():g}"]
        if self.no_labels.isChecked():
            cmd.append("--no-labels")
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{dataset.name}.log"
        with open(log_path, "w") as log_file:
            subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=HERE)
        self.log.appendPlainText(f"▶ {dataset.name}  (bin {self.bin.value()}) — loading…")


def main():
    app = QApplication(sys.argv)
    window = Launcher()
    window.show()
    # Folders dropped onto the desktop shortcut arrive as command-line arguments.
    if len(sys.argv) > 1:
        window.open_paths([Path(a) for a in sys.argv[1:]])
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
