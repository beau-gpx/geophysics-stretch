# SDP Imaging for QGIS

*SDP = Spatial Data Portal. Formerly called Stretch Editor.*

Interactive, ER Mapper-style colour stretching for single-band grids: magnetics, gravity,
radiometrics, DEMs and anything else you image with a colour ramp.

Edit a transfer curve directly over the data histogram, see the result live on the map, and export
a georeferenced image with a transparent collar and a matching colour bar.

## Features

- **Curve editor over the histogram:** add, drag, merge and delete nodes, with undo/redo.
- **Presets:** Linear, Histogram-equalised and Log-linear, with an adjustable number of points.
- **Clip limits:** by percentile (separate lower and upper) or by exact data values, with one-click reset.
- **Mirror about a centre value:** symmetric stretches for grids that straddle zero (e.g. 1VD), with
  width and slope controls.
- **Flexible view:** data or curve extent, zoom and pan, log value axis and log counts.
- **Live styling:** the layer updates as you edit. Your stretch is saved with the layer and project.
- **Image export:** Cloud-Optimised GeoTIFF, GeoTIFF, JPEG2000, PNG or JPEG. Choose compression,
  lossy or lossless, quality, transparency, and output cell size.
- **Colour bar export:** PNG, SVG or PDF, with a live preview.
- **Ternary (RGB) images:** e.g. radiometric K, Th and U as red, green and blue, each channel with its
  own curve, presets and clip limits, plus a triangle legend.
- **Layers panel sync:** the grid you're editing is selected and scrolled into view.

## Install

1. Download `stretch_editor-<version>.zip` from the
   [latest release](https://github.com/beau-gpx/geophysics-stretch/releases/latest). Don't unzip it.
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**, choose the file and
   click **Install Plugin**. Installing a newer ZIP replaces the old version.
3. Open the editor from its toolbar button or **Raster → SDP Imaging**. It docks on the right.

Requires QGIS 3.22 or later, including QGIS 4, on Windows, macOS or Linux. There are no extra
dependencies: it uses NumPy and GDAL, which come with QGIS.

## Quick start

1. Select a single-band raster in the Layers panel. The editor opens on it. No grid to hand? Use
   **Raster → SDP Imaging → Load sample data** (see below).
2. Click **Hist. equalise** (or Linear / Log-linear).
3. Adjust the **Clip limits**, or drag nodes on the curve. The map updates as you go.
4. Use **Export image…**, **Colour bar…** or **Save style…** when you're happy with it.

Opening a grid never changes its existing style. Nothing is applied until you edit or press **Apply**.

## Using the editor

### The curve
The curve maps data values (x-axis) to positions on the colour ramp (y-axis). The ramp runs up the
left side, and the strip under the x-axis shows the colour each data value gets.

| Action | How |
| --- | --- |
| Add a node | Click an empty spot |
| Move a node | Drag it, or type exact values under **Selected node** |
| Merge two nodes | Drag one onto its neighbour (red ring), then release |
| Delete a node | Right-click it, or select it and press Delete |
| Undo / redo | Buttons, or Ctrl+Z / Ctrl+Y with the curve focused |
| Zoom the x-axis | Shift + mouse wheel |
| Pan the x-axis | Shift + drag, or middle-drag |

**Points** sets the number of nodes (presets start with 32). On an untouched preset it rebuilds the
preset. On a hand-edited curve, adding points keeps the shape exactly and removing points drops the
least important nodes first.

### View
- **Data:** shows the full data range.
- **Curve:** fits exactly to the first and last nodes, and keeps fitting as the clip limits change.
- Typing a range, zooming or panning gives a free view that stays where you put it.
- Nodes outside the view show as orange arrows at the edge.
- **Log counts (Y)** log-scales the bar heights. **Log values (X)** puts data values on a log axis;
  data with zero or negative values uses a symmetric log. Both only change the display.

### Clip limits
- **Percentile:** lower and upper percentiles, e.g. 5 % to 80 %. The default 0 % to 100 % is the
  data minimum to maximum.
- **Values:** exact minimum and maximum data values.
- **Reset:** back to Percentile 0 % to 100 %.

Changing the limits rebuilds an untouched preset, or stretches a hand-edited curve to the new range
while keeping its shape. A grid styled outside the editor starts from its existing min/max.

### Mirror about centre (Advanced)
For grids that straddle zero, open **Advanced** and tick **Mirror about centre**. Equal positive
and negative values then get mirrored colours.

- **Centre:** any value, or one click for **0** or the data **Median**. It sits mid-ramp and its node is fixed.
- **Presets** work on distance from the centre, so Hist. equalise balances both sides.
- **Edits** on one side are copied to the other. Points step by two.
- **Width ±:** the half-width around the centre (clip limits become centre ± width).
- **Slope:** contrast around the centre. Above 1 makes small values stand out; below 1 puts more
  contrast in the tails.

### Colour and styling
- **Colour ramp:** any QGIS ramp. The default is an ER Mapper-style pseudocolour.
- **Live update** restyles the layer as you edit; untick it and use **Apply** on very large grids.
- The curve, clip limits, view and ramp are saved with the layer, so they come back with the project.
- **Save style…** writes a QGIS `.qml` style you can load onto other layers.
- The layer's legend in print layouts shows the stretch as a continuous ramp.

### Ternary images (RGB)
Combine three grids as red, green and blue, e.g. radiometric potassium, thorium and uranium.

The top of the panel has two tabs: **Single grid** and **Ternary (RGB)**. The curve editor below works
on whichever is selected.

1. Open the **Ternary (RGB)** tab. Under **New ternary layer**, pick the grid for **Red**, **Green** and
   **Blue**. **Active** next to each one takes the layer selected in the Layers panel; on this tab,
   selecting ordinary grids in the Layers panel doesn't open them in the editor, so you can click
   through them freely. **Guess K / Th / U** picks layers named like K, Th and U (or potassium,
   thorium, uranium), or the first three bands of a multi-band grid selected in the Layers panel.
   A band list appears for multi-band grids.
2. Click **Create…** and choose where to save it. It's a small `.vrt` file that points at your grids;
   nothing is copied. The layer is added to the map and opened in the editor.
3. Later, pick it from the **Layer** list on the Ternary tab, or select it in the Layers panel.

Each channel starts as **Linear** from the 1 % to 99 % percentiles. Use the **R / G / B** buttons on the
Ternary tab to
choose the channel to edit: it gets its own histogram, curve, presets, clip limits, mirror settings
and undo. The strip under the histogram shows that channel's colour. **Invert (CMY)** swaps to cyan,
magenta and yellow on white, which suits printing.

- A pixel with nodata in any of the three grids is transparent.
- The grids must share a coordinate system. They can have different extents or cell sizes: the
  ternary layer covers all three at the finest cell size.
- The curves are stored in the `.vrt` itself, so it shows the same in any GIS that reads GDAL
  virtual rasters, with or without this plugin. Keep it with (or near) the grids: it finds them by
  a relative path.
- **Export image…** works as for a single grid. **Ternary legend…** (in place of Colour bar…) saves a
  triangle legend with the channel names as PNG, SVG or PDF, and *Also save a colour bar* in the
  export dialog saves it beside the image.

The sample data has potassium but no thorium or uranium grids, so to try it, use the three sample
grids as stand-ins.

## Exporting

### Image
| Option | Choices |
| --- | --- |
| Format | Cloud-Optimised GeoTIFF, tiled GeoTIFF, JPEG2000, PNG + world file, JPEG + world file |
| Compression | WEBP, JPEG, ZSTD, DEFLATE, LZW or none (GeoTIFF formats) |
| Mode | Lossy or lossless, where the compression supports both |
| Quality | 1–100 for JPEG/WEBP; target size % for JPEG2000; level for ZSTD/DEFLATE/PNG |
| Transparency | Alpha channel, 1-bit mask, or none. The background colour (default white) fills the nodata collar: with a mask it shows only in viewers that ignore masks, such as Windows Explorer and Teams |
| Resolution | Cell size in map units (default: the grid's own) or scale 1–1000 %, with resampling |
| Extras | Overviews, add to map, and a matching colour bar saved alongside |

Options your QGIS can't write are greyed out, and a note explains the trade-offs of each choice.
Good defaults: **WEBP lossy COG** for the smallest files in QGIS, **JPEG COG with a mask** for older
software, **PNG** or **JPEG** for reports and slides.

### Colour bar
**Colour bar…** saves a legend as PNG, SVG or PDF. You can set the title, units, orientation, size,
number of labels, decimals, text size and background. Labels can be *evenly spaced along the bar*
(best for histogram-equalised stretches) or *round numbers* (best for linear ones).

## Sample data
**Raster → SDP Imaging → Load sample data** adds three small synthetic grids in a group, zooms to
them and opens the editor:

| Grid | What it is | Good for trying |
| --- | --- | --- |
| Sample TMI (nT) | Total magnetic intensity: buried bodies, dykes and a faulted unit | Hist. equalise, colour bar |
| Sample TMI 1VD (nT/m) | Its first vertical derivative, straddling zero | Mirror about centre, Slope |
| Sample potassium (%) | Radiometric potassium, all positive and skewed | Log-linear, Log values (X) |

Each is 400 × 320 cells of 50 m, with nodata outside an irregular survey outline (handy for testing
transparent exports). The grids are made up by `scripts/make_sample_data.py`, sit at arbitrary
coordinates, and are free to use for any purpose (CC0). They live in `stretch_editor/sample_data/`.

## Tips
- **Sun shading:** duplicate the grid, style the copy as *Hillshade*, put it above the coloured
  layer and set its blending mode to *Multiply*.
- **Nodata:** the layer's nodata value and dummy values beyond ±1e30 are left transparent.

## Development

```
stretch_editor/          the plugin (this folder is what goes in the ZIP)
  plugin.py              toolbar button and menu entry
  core/                  pure maths: curves and presets, colour bar labels, export options, ternary VRTs
  ui/                    the panel, curve editor and dialogs
  layers.py              reading raster data and layer helpers
  styling.py             colour ramps and applying a curve as a layer style
  state.py               settings saved with each layer
  legend.py              drawing the colour bar and the ternary legend
  compat.py              QGIS 3 / QGIS 4 compatibility helpers
  sample_data/           synthetic test grids (GeoTIFF)
tests/                   unit tests for core/ and the sample data (no QGIS needed)
scripts/build_zip.py     builds the installable ZIP into dist/ and checks it against QGIS repository rules
scripts/make_sample_data.py  regenerates the sample grids (needs numpy and tifffile)
scripts/check_imports.py     imports every module against stub QGIS (no QGIS needed)
```

```
python -m unittest discover -s tests     # run the tests
ruff check .                             # lint
python scripts/check_imports.py          # offline import check
python scripts/build_zip.py              # build dist/stretch_editor-<version>.zip
```

Issues and suggestions: [GitHub issues](https://github.com/beau-gpx/geophysics-stretch/issues).

## Licence
Copyright (C) 2026 Beau Garland. Contact: beau.gpx@pm.me

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 2 of the
License, or (at your option) any later version. It is distributed in the hope that it will be
useful, but WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for the full text.
