"""View a Squid z-stack in napari with a white tick-marked bounding box and an adjustable z range.

All channels in the acquisition are loaded as separate additive layers, colored with each
channel's display_color from acquisition.yaml.

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
import yaml
from napari.utils import Colormap
from qtpy.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from superqt import QLabeledDoubleRangeSlider

OBJ_MAG = 20.0
OBJ_DESIGN_TUBE_F_MM = 180.0  # Olympus
TUBE_F_MM = 200.0  # Nikon
SENSOR_PIXEL_UM = 6.5
PIXEL_UM = SENSOR_PIXEL_UM / (OBJ_MAG * TUBE_F_MM / OBJ_DESIGN_TUBE_F_MM)

BOX_COLOR = "white"
FALLBACK_COLORS = ["#1FFF00", "#FF00FF", "#00FFFF", "#FFFF00", "#FF4040", "#4080FF"]

# <region>_<fov>_<z>_<channel>.tiff, e.g. current_0_12_Fluorescence_488_nm_Ex.tiff
FILE_RE = re.compile(r"^(?P<region>.+)_(?P<fov>\d+)_(?P<z>\d+)_(?P<channel>[A-Za-z].*)\.tiff?$")


def channel_colors(dataset: Path) -> dict[str, str]:
    """Map channel name (spaces -> underscores, as in filenames) to its display color."""
    try:
        cfg = yaml.safe_load((dataset / "acquisition.yaml").read_text())
        return {c["name"].replace(" ", "_"): c["display_color"] for c in cfg.get("channels", [])}
    except Exception:
        return {}


def short_name(channel: str) -> str:
    m = re.search(r"(\d+)_?nm", channel)
    return f"{m.group(1)} nm" if m else channel.replace("_", " ")


def wavelength(channel: str) -> float:
    m = re.search(r"(\d+)_?nm", channel)
    return float(m.group(1)) if m else math.inf


def load_channels(dataset: Path, binning: int) -> tuple[dict[str, np.ndarray], float]:
    """Return ({channel: (z, y, x) stack}, dz_um) for the first region/FOV in the acquisition."""
    params = json.loads((dataset / "acquisition parameters.json").read_text())
    dz_um = float(params["dz(um)"])

    entries = []
    for path in (dataset / "0").glob("*.tif*"):
        m = FILE_RE.match(path.name)
        if m:
            entries.append((m["region"], int(m["fov"]), int(m["z"]), m["channel"], path))
    if not entries:
        raise SystemExit(f"no <region>_<fov>_<z>_<channel>.tiff images found in {dataset / '0'}")
    region, fov = min((r, f) for r, f, *_ in entries)
    if len({(r, f) for r, f, *_ in entries}) > 1:
        print(f"multiple regions/FOVs found; showing region '{region}' FOV {fov}")

    by_channel: dict[str, list[tuple[int, Path]]] = {}
    for r, f, z, ch, path in entries:
        if (r, f) == (region, fov):
            by_channel.setdefault(ch, []).append((z, path))

    def read(path):
        img = tifffile.imread(path)
        if binning > 1:
            h, w = (s // binning * binning for s in img.shape)
            img = img[:h, :w].reshape(h // binning, binning, w // binning, binning).mean(axis=(1, 3))
        return img.astype(np.uint16)

    stacks = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for ch in sorted(by_channel, key=wavelength):
            files = [p for _, p in sorted(by_channel[ch])]
            stacks[ch] = np.stack(list(pool.map(read, files)))
    return stacks, dz_um


def mip_contrast(stack: np.ndarray) -> tuple[float, float]:
    """Contrast limits suited to MIP rendering: percentiles of the z max-projection, not of voxels."""
    step = max(1, stack.shape[-1] // 800)
    mip = stack[:, ::step, ::step].max(axis=0)
    lo, hi = np.percentile(mip, [5, 99.5])
    return float(lo), float(max(hi, lo + 1))


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
    def __init__(self, viewer, images, box_layer, label_layer, nz, dz, Y, X, show_numbers=True):
        super().__init__()
        self.viewer, self.images = viewer, images
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
        self.info.setWordWrap(True)
        self.numbers_cb = QCheckBox("Tick numbers")
        self.numbers_cb.setChecked(show_numbers)
        self.titles_cb = QCheckBox("Axis titles")
        self.titles_cb.setChecked(show_numbers)
        for cb in (self.numbers_cb, self.titles_cb):
            cb.toggled.connect(lambda _: self.update(self.slider.value()))
        auto_btn = QPushButton("Auto contrast (this z range)")
        auto_btn.clicked.connect(self.auto_contrast)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Z range (µm, from bottom plane)"))
        layout.addWidget(self.slider)
        layout.addWidget(self.info)
        labels_row = QHBoxLayout()
        labels_row.addWidget(self.numbers_cb)
        labels_row.addWidget(self.titles_cb)
        layout.addLayout(labels_row)
        layout.addWidget(auto_btn)
        layout.addStretch()
        self.update(self.slider.value())

    def z_indices(self) -> tuple[int, int]:
        k0, k1 = (int(round(v / self.dz)) for v in self.slider.value())
        return min(k0, k1), max(k0, k1)

    def auto_contrast(self):
        k0, k1 = self.z_indices()
        for image in self.images:
            image.contrast_limits = mip_contrast(image.data[k0 : k1 + 1])

    def update(self, value=None):
        k0, k1 = self.z_indices()
        # Clipping plane positions are interpreted in world (um) coordinates here.
        for image in self.images:
            image.experimental_clipping_planes = [
                {"position": ((k0 - 0.5) * self.dz, 0, 0), "normal": (1, 0, 0), "enabled": True},
                {"position": ((k1 + 0.5) * self.dz, 0, 0), "normal": (-1, 0, 0), "enabled": True},
            ]
        segs, pts, txt = build_box(k0 * self.dz, k1 * self.dz, self.Y, self.X)
        # Vectors layer data: (N, 2, 3) = [start, displacement]
        self.box_layer.data = np.stack([segs[:, 0], segs[:, 1] - segs[:, 0]], axis=1)
        show_numbers, show_titles = self.numbers_cb.isChecked(), self.titles_cb.isChecked()
        txt = [t if (show_titles if t.endswith("(µm)") else show_numbers) else "" for t in txt]
        self.label_layer.data = pts
        self.label_layer.text = {"string": txt, "color": BOX_COLOR, "size": 11, "anchor": "center"}
        self.info.setText(f"planes {k0}–{k1} of 0–{self.nz - 1}  ({(k1 - k0) * self.dz:g} µm)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--bin", type=int, default=2, help="XY binning for display (1 = full res, needs lots of GPU memory)")
    ap.add_argument("--z-scale", type=float, default=1.0,
                    help="multiply stage dz by this (e.g. refractive-index focal-shift correction)")
    ap.add_argument("--no-labels", action="store_true", help="start with tick numbers and axis titles hidden")
    args = ap.parse_args()

    stacks, dz = load_channels(args.dataset, args.bin)
    dz *= args.z_scale
    px = PIXEL_UM * args.bin
    nz, ny, nx = next(iter(stacks.values())).shape
    Y, X = ny * px, nx * px
    print(f"channels {list(stacks)}, stack {(nz, ny, nx)}, pixel {px:.4f} um, dz {dz:g} um, "
          f"extent z={(nz-1)*dz:g} y={Y:.1f} x={X:.1f} um")

    colors = channel_colors(args.dataset)
    viewer = napari.Viewer(ndisplay=3, title=args.dataset.name)
    images = []
    for i, (ch, stack) in enumerate(stacks.items()):
        if stack.shape != (nz, ny, nx):
            print(f"skipping {ch}: shape {stack.shape} != {(nz, ny, nx)}")
            continue
        color = colors.get(ch, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
        cmap = Colormap([[0, 0, 0, 1], color], name=f"{short_name(ch)} {color}")
        images.append(viewer.add_image(
            stack, name=short_name(ch), scale=(dz, px, px), colormap=cmap,
            contrast_limits=mip_contrast(stack), rendering="mip", blending="additive",
        ))
    box = viewer.add_vectors(
        np.zeros((0, 2, 3)), ndim=3, name="bounding box", edge_width=0.002 * max(Y, X, nz * dz),
        edge_color=BOX_COLOR, length=1, vector_style="line",
    )
    labels = viewer.add_points(
        np.zeros((0, 3)), name="box labels", size=0, face_color="transparent",
        border_width=0, ndim=3,
    )
    widget = ZRangeWidget(viewer, images, box, labels, nz, dz, Y, X, show_numbers=not args.no_labels)
    viewer.window.add_dock_widget(widget, name="Z range", area="right")
    viewer.layers.selection.active = images[-1]
    viewer.scale_bar.visible = True
    viewer.scale_bar.unit = "um"
    viewer.reset_view()
    viewer.camera.angles = (0, -60, 60)
    viewer.camera.zoom *= 0.6
    napari.run()


if __name__ == "__main__":
    main()
