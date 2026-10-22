# squid-zstack-napari

Open a Squid z-stack acquisition in napari as a 3D volume with:

- a white bounding box with tick marks and µm labels on x, y and z
- a **Z range** dock widget (two-handle slider, µm from the bottom plane) that clips the rendered volume and redraws the box/ticks to match
- checkboxes in the same widget to show/hide the tick numbers and axis titles

## Optics

Pixel size is computed for an Olympus 20x objective (designed for f = 180 mm) used with a Nikon f = 200 mm tube lens:

```
magnification = 20 × 200 / 180 = 22.22×
pixel size    = 6.5 µm / 22.22 = 0.2925 µm
```

This overrides the pixel size in the acquisition metadata (which assumes a 180 mm tube lens). Edit the constants at the top of `view_stack.py` for other optics.

## Usage

```
pip install -r requirements.txt
python view_stack.py <dataset_dir> [--bin 2] [--z-scale 1.0] [--no-labels]
```

- `dataset_dir` — Squid acquisition folder containing `acquisition parameters.json` and `0/current_0_<z>_*.tiff`
- `--bin` — XY binning used for display (default 2; `1` = full resolution, needs a lot of GPU memory for large stacks)
- `--z-scale` — multiply the stage z step, e.g. to correct for refractive-index focal shift
- `--no-labels` — start with tick numbers and axis titles hidden (box and tick marks stay)

Z step is read from `dz(um)` in `acquisition parameters.json`.
