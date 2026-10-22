# Changelog

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
