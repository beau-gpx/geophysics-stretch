# Changelog

## v1.2 — 2026-10-22
- Export resolution by exact cell size (finer or coarser) or scale up to 1000 %, with
  nearest / bilinear / cubic / average resampling.
- Presets default to 32 points.
- Clip limits default to 0 % / 100 % (data min and max).
- Separate lower and upper percentile clips (e.g. 5 % to 80 %).
- Histogram opens at the full data range.
- Manual x-axis view range: View fields, mouse-wheel zoom, Shift/middle-drag pan, Data and
  Curve buttons; off-screen nodes shown as edge markers.
- Dragging a node onto its neighbour merges the two.

## v1.1 — 2026-10-22
- Clip limits by manual Min/Max values as well as percent.
- **Points** field to set the number of curve nodes (rebuilds unedited presets; shape-preserving
  resample for edited curves).
- Detailed export dialog: GeoTIFF/COG, JPEG2000, PNG and JPEG; WEBP/JPEG/ZSTD/DEFLATE/LZW;
  lossy or lossless; quality, target size and compression level; alpha, 1-bit mask or fill
  colour; output resolution; overviews; settings remembered.
- Undo/redo (buttons, Ctrl+Z / Ctrl+Y), and Delete key to remove the selected node.

## v1.0 — 2026-10-22
- First release: histogram with editable transfer curve, Linear / Hist. equalise / Log-linear
  presets with percent clip, live layer styling, curve saved with the layer, RGBA COG export
  (WEBP, JPEG + mask, DEFLATE), .qml style export.
