"""View a Squid z-stack in napari with a white tick-marked bounding box and an adjustable z range.

Optics: Olympus 20x (designed for f=180 mm) used with a Nikon f=200 mm tube lens,
so effective magnification = 20 * 200/180 = 22.22x -> 6.5 um / 22.22 = 0.2925 um/px.

Usage: python view_stack.py <dataset_dir> [--bin 2] [--z-scale 1.0]
"""

import argparse
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import napari
import numpy as np
import tifffile
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget
from superqt import QLabeledDoubleRangeSlider

OBJ_MAG = 20.0
OBJ_DESIGN_TUBE_F_MM = 180.0  # Olympus
TUBE_F_MM = 200.0  # Nikon
SENSOR_PIXEL_UM = 6.5
PIXEL_UM = SENSOR_PIXEL_UM / (OBJ_MAG * TUBE_F_MM / OBJ_DESIGN_TUBE_F_MM)

BOX_COLOR = "white"


def load_stack(dataset: Path, binning: int) -> tuple[np.ndarray, float]:
    params = json.loads((dataset / "acquisition parameters.json").read_text())
    dz_um = float(params["dz(um)"])
    files = sorted(
        (dataset / "0").glob("current_0_*_*.tiff"),
        key=lambda p: int(re.match(r"current_0_(\d+)_", p.name).group(1)),
    )

    def read(path):
        img = tifffile.imread(path)
        if binning > 1:
            h, w = (s // binning * binning for s in img.shape)
            img = img[:h, :w].reshape(h // binning, binning, w // binning, binning).mean(axis=(1, 3))
        return img.astype(np.uint16)

    with ThreadPoolExecutor(max_workers=16) as pool:
        planes = list(pool.map(read, files))
    return np.stack(planes), dz_um


def nice_step(extent: float, target_ticks: int = 5) -> float:
    raw = extent / target_ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def ticks_for(lo: float, hi: float) -> np.ndarray:
    step = nice_step(hi - lo)
    return np.arange(math.ceil(lo / step) * step, hi + 1e-9, step)


def build_box(z0: float, z1: float, Y: float, X: float):
    """Return (line segments, label positions, label strings) in world (z, y, x) um."""
    corners = lambda z: [(z, 0, 0), (z, 0, X), (z, Y, X), (z, Y, 0)]
    segs = []
    for z in (z0, z1):
        c = corners(z)
        segs += [(c[i], c[(i + 1) % 4]) for i in range(4)]
    segs += [((z0, y, x), (z1, y, x)) for (_, y, x) in corners(z0)]

    tick_len = 0.02 * max(z1 - z0, Y, X)
    label_off = 3 * tick_len
    pts, txt = [], []

    # x ticks along the edge (z0, Y, x), pointing +y
    for x in ticks_for(0, X):
        segs.append(((z0, Y, x), (z0, Y + tick_len, x)))
        pts.append((z0, Y + label_off, x)); txt.append(f"{x:g}")
    pts.append((z0, Y + 2.2 * label_off, X / 2)); txt.append("x (µm)")

    # y ticks along the edge (z0, y, 0), pointing -x
    for y in ticks_for(0, Y):
        segs.append(((z0, y, 0), (z0, y, -tick_len)))
        pts.append((z0, y, -label_off)); txt.append(f"{y:g}")
    pts.append((z0, Y / 2, -2.2 * label_off)); txt.append("y (µm)")

    # z ticks along the vertical edge (z, Y, X), pointing +y
    for z in ticks_for(z0, z1):
        segs.append(((z, Y, X), (z, Y + tick_len, X)))
        pts.append((z, Y + label_off, X)); txt.append(f"{z:g}")
    pts.append(((z0 + z1) / 2, Y + 2.2 * label_off, X)); txt.append("z (µm)")

    return np.array(segs, dtype=float), np.array(pts, dtype=float), txt


class ZRangeWidget(QWidget):
    def __init__(self, viewer, image, box_layer, label_layer, nz, dz, Y, X):
        super().__init__()
        self.viewer, self.image = viewer, image
        self.box_layer, self.label_layer = box_layer, label_layer
        self.nz, self.dz, self.Y, self.X = nz, dz, Y, X

        self.slider = QLabeledDoubleRangeSlider()
        self.slider.setOrientation(1)  # horizontal
        self.slider.setRange(0, (nz - 1) * dz)
        self.slider.setSingleStep(dz)
        self.slider.setDecimals(0)
        self.slider.setValue((0, (nz - 1) * dz))
        self.slider.valueChanged.connect(self.update)

        self.info = QLabel()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Z range (µm, from bottom plane)"))
        layout.addWidget(self.slider)
        layout.addWidget(self.info)
        layout.addStretch()
        self.update(self.slider.value())

    def update(self, value):
        k0 = int(round(value[0] / self.dz))
        k1 = int(round(value[1] / self.dz))
        if k1 < k0:
            k0, k1 = k1, k0
        # Clipping plane positions are interpreted in world (um) coordinates here.
        self.image.experimental_clipping_planes = [
            {"position": ((k0 - 0.5) * self.dz, 0, 0), "normal": (1, 0, 0), "enabled": True},
            {"position": ((k1 + 0.5) * self.dz, 0, 0), "normal": (-1, 0, 0), "enabled": True},
        ]
        segs, pts, txt = build_box(k0 * self.dz, k1 * self.dz, self.Y, self.X)
        # Vectors layer data: (N, 2, 3) = [start, displacement]
        self.box_layer.data = np.stack([segs[:, 0], segs[:, 1] - segs[:, 0]], axis=1)
        self.label_layer.data = pts
        self.label_layer.text = {"string": txt, "color": BOX_COLOR, "size": 11, "anchor": "center"}
        self.info.setText(f"planes {k0}–{k1} of 0–{self.nz - 1}  ({(k1 - k0) * self.dz:g} µm)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--bin", type=int, default=2, help="XY binning for display (1 = full res, ~8 GB)")
    ap.add_argument("--z-scale", type=float, default=1.0,
                    help="multiply stage dz by this (e.g. refractive-index focal-shift correction)")
    args = ap.parse_args()

    stack, dz = load_stack(args.dataset, args.bin)
    dz *= args.z_scale
    px = PIXEL_UM * args.bin
    nz, ny, nx = stack.shape
    Y, X = ny * px, nx * px
    print(f"stack {stack.shape}, pixel {px:.4f} um, dz {dz:g} um, extent z={(nz-1)*dz:g} y={Y:.1f} x={X:.1f} um")

    lo, hi = np.percentile(stack[:: max(1, nz // 20), ::4, ::4], [0.5, 99.95])
    viewer = napari.Viewer(ndisplay=3, title=args.dataset.name)
    image = viewer.add_image(
        stack, name="488 nm", scale=(dz, px, px), colormap="green",
        contrast_limits=(float(lo), float(hi)), rendering="mip", blending="additive",
    )
    box = viewer.add_vectors(
        np.zeros((0, 2, 3)), ndim=3, name="bounding box", edge_width=0.002 * max(Y, X, nz * dz),
        edge_color=BOX_COLOR, length=1, vector_style="line",
    )
    labels = viewer.add_points(
        np.zeros((0, 3)), name="box labels", size=0, face_color="transparent",
        border_width=0, ndim=3,
    )
    widget = ZRangeWidget(viewer, image, box, labels, nz, dz, Y, X)
    viewer.window.add_dock_widget(widget, name="Z range", area="right")
    viewer.layers.selection.active = image
    viewer.scale_bar.visible = True
    viewer.scale_bar.unit = "um"
    viewer.reset_view()
    viewer.camera.angles = (0, -60, 60)
    viewer.camera.zoom *= 0.6
    napari.run()


if __name__ == "__main__":
    main()
