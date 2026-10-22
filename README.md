# Stretch Editor (QGIS plugin)

ER Mapper-style colour stretch for single-band grids (mag, gravity, radiometrics, DEMs).

## Install / update
1. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP**
2. Choose `stretch_editor.zip` → **Install Plugin** (this replaces an older version)
3. Open it from the toolbar icon or **Raster → Stretch Editor**. It docks on the right.

## Choosing the grid
- Pick the layer and band at the top. With **Sync with Layers panel** ticked (the default), the
  grid you pick is selected in the Layers panel, with its group expanded and scrolled into view,
  and selecting a raster in the Layers panel opens it in the editor.

## Editing the curve
- The panel shows the data histogram and the transfer curve (data value → position along the
  colour ramp). The colour ramp runs up the y-axis, and a strip under the x-axis shows the
  colour each data value gets.
- Click to add a node, drag to move it, right-click (or select + Delete) to remove it.
  Drag a node onto its neighbour (it gets a red ring) and release to merge the two.
  Type exact values in *Selected node*.
- **Undo / Redo** buttons, or Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) after clicking on the curve.
- **Presets:** Linear, Hist. equalise, Log-linear.
- **Points:** the number of nodes on the curve (presets start with 32).
  - On an unedited preset it rebuilds the preset with that many points (each preset
    remembers its own count).
  - On a hand-edited curve it resamples: adding points keeps the shape exactly; removing
    points drops the least important nodes first so bends survive.
- **Log counts (Y)** log-scales the histogram bar heights, which helps with spiky data.
- **Log values (X)** shows data values on a log axis. Data with zero or negative values (e.g.
  magnetic anomalies) uses a symmetric log, linear near zero. This only changes the display;
  the stretch itself is unchanged.

## View range
- The histogram opens showing the full data range (min to max).
- Set the x-axis range exactly with the **View** fields, zoom with the mouse wheel, or pan with
  Shift+drag or middle-drag. **Data** resets to min–max; **Curve** sets the view to exactly the first and last nodes.
- Nodes outside the view are shown as orange arrows at the edge.

## Clip limits
- **Percentile:** separate lower and upper percentiles, e.g. 5 % to 80 %. The default
  0 % to 100 % is the data minimum and maximum. The resulting values are shown below.
- **Values:** type exact Min / Max data values (pre-filled from the current curve).
- Changing the limits rebuilds an unedited preset, or stretches a hand-edited curve to the
  new range while keeping its shape.

## Colour and saving
- **Colour ramp:** any QGIS ramp (default is an ER Mapper-like pseudocolour); invert it from
  the button's menu.
- **Live update** restyles the layer as you edit. The curve, clip settings and ramp are saved
  with the layer, so they come back when you reopen the project.
- **Save style (.qml)** saves the stretch as a QGIS style for reuse.

## Colour bar
- **Colour bar…** saves a colour bar / legend for the current stretch as PNG, SVG (vector,
  editable) or PDF, with a live preview.
- Options: title and units, vertical or horizontal, bar length and thickness, number of labels,
  label spacing (evenly along the bar, which suits histogram-equalised stretches, or round
  numbers), decimals, text size, transparent or white background, PNG resolution.
- The layer's legend in QGIS print layouts also shows the stretch as a continuous ramp.

## Export image
Choose in the export dialog (your last settings are remembered):
- **Format:** Cloud-Optimised GeoTIFF, tiled GeoTIFF, JPEG2000, PNG + world file, JPEG + world file
- **Compression:** WEBP, JPEG, ZSTD, DEFLATE, LZW or none (GeoTIFF formats)
- **Mode:** lossy or lossless where the compression supports both
- **Quality** (JPEG/WEBP 1–100), **target size %** (JPEG2000) or **compression level** (ZSTD/DEFLATE/PNG)
- **Transparency:** alpha channel (smooth edges), 1-bit internal mask, or none with a fill colour
- **Resolution:** an exact **cell size** in map units (the default, starting at the grid's native
  cell) or a scale (1–1000 % of native), finer or coarser than the grid, with nearest, bilinear, cubic or average resampling. The output size
  and cell size are shown.
- **Overviews** for fast display, **add to map** when done, and **also save a colour bar**
  next to the image (using your colour bar settings)

Options this QGIS's GDAL can't write are greyed out, and a note under the options explains the
trade-offs of the current choice.

## Notes
- For a sun-shaded look, duplicate the grid, style the copy as *Hillshade*, put it above
  the coloured layer and set its blending mode to *Multiply*.
- Values beyond ±1e30 and the layer's nodata value are treated as transparent.
- Works with QGIS 3.22 or later, including QGIS 4 (Qt6).
