# Stretch Editor — notes for Claude Code

QGIS plugin giving ER Mapper-style interactive colour stretching for single-band geophysics grids
(magnetics, 1VD, gravity, radiometrics). Owner: Beau Garland. Public repo, GPL-2.0-or-later.
The README is the user guide; CHANGELOG.md records every version and the reasons for changes.

## Layout
- `stretch_editor/` is the plugin package and exactly what ships in the ZIP.
  - `core/` pure Python + numpy, no QGIS/Qt imports (curve maths, presets, mirror mode,
    colour bar labels, export options and the GDAL export loop). Keep it that way so it stays testable.
  - `ui/dock.py` the panel (layout in `_build_ui`, signals in `_connect`, then grouped handlers);
    `ui/curve_widget.py` the histogram/curve editor; `ui/export_dialog.py`, `ui/colourbar_dialog.py`.
  - `layers.py` raster reading and layer helpers; `styling.py` ramps and applying a curve as a
    pseudocolour style; `state.py` per-layer saved settings (JSON custom property, with upgrades
    for older formats); `legend.py` colour bar drawing; `compat.py` QGIS 3 (Qt5) / QGIS 4 (Qt6) helpers.
  - `sample_data/` synthetic CC0 GeoTIFFs (regenerate with `scripts/make_sample_data.py`).
- `tests/` unittest suite (no QGIS needed). `scripts/` build, sample data, offline import check.

## Commands
```
python -m unittest discover -s tests     # unit tests (sample-data checks need tifffile)
ruff check .                             # lint (config in ruff.toml)
python scripts/check_imports.py          # imports every module against stub qgis/Qt; no QGIS needed
python scripts/build_zip.py              # dist/stretch_editor-<version>.zip, checked against QGIS repo rules
```
Run all four before committing. None of them exercise real Qt/QGIS behaviour: when a change touches
the UI, styling or export, test it in QGIS (Plugins > Install from ZIP, then Raster > Stretch Editor >
Load sample data) or say clearly that it hasn't been run in QGIS.

## Conventions
- Must run on QGIS 3.22+ (Python 3.9+) and QGIS 4 (Qt6). Use `compat.E(Qt, 'Scope.Name')` for Qt
  enums and `compat.first_attr(...)` for QGIS enums that moved; import Qt via `qgis.PyQt`.
- No dependencies beyond what QGIS ships (numpy, GDAL). No binaries in the package.
- Every source file starts with the SPDX GPL-2.0-or-later header and the copyright line.
- Opening a grid must never restyle it; only an edit, preset, clip/ramp change or Apply does.
- Saved layer state must stay backward compatible: upgrade old formats in `state.load()`.
- UI text is plain English, Australian spelling (colour, normalise).

## Releasing
1. Bump `version=` and `changelog=` in `stretch_editor/metadata.txt`; add a CHANGELOG.md entry.
2. Run the four checks, commit, push to `main`.
3. Beau creates the GitHub release (tag `vX.Y.Z`, notes, attach the built ZIP) and uploads the same
   ZIP to plugins.qgis.org. Write the release notes for him; the Releases page is what colleagues
   are sent (`/releases/latest`).

## Commit messages
Plain descriptive messages, optionally a `Co-Authored-By:` line. Do not add `Claude-Session:` lines
(they were deliberately removed from the history).

## Not in the repo
A real NSW survey subset (AIR0827 West Wyalong TMI + 1VD) was offered as sample data but is on hold
until its redistribution licence is confirmed with the Geological Survey of NSW. Don't add real
survey data without a confirmed licence and attribution.
