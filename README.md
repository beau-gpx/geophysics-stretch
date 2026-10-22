# Stretch Editor (QGIS plugin) — v1.1

ER Mapper-style colour stretch for single-band grids (mag, gravity, radiometrics, DEMs).

## Install / update
1. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP**
2. Choose `stretch_editor.zip` → **Install Plugin** (this replaces an older version)
3. Open it from the toolbar icon or **Raster → Stretch Editor**. It docks on the right.

## Editing the curve
- The panel shows the data histogram, the transfer curve (data value → position along the
  colour ramp) and a colour strip showing the result.
- Click to add a node, drag to move it, right-click (or select + Delete) to remove it.
  Type exact values in *Selected node*.
- **Undo / Redo** buttons, or Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) after clicking on the curve.
- **Presets:** Linear, Hist. equalise, Log-linear.
- **Points:** the number of nodes on the curve.
  - On an unedited preset it rebuilds the preset with that many points (each preset
    remembers its own count).
  - On a hand-edited curve it resamples: adding points keeps the shape exactly; removing
    points drops the least important nodes first so bends survive.
- **Log histogram** helps with spiky data; **Full range** shows min–max instead of 0.1–99.9 %.

## Clip limits
- **Percent:** clip a percentage of the data at each end (the resulting values are shown).
- **Values:** type exact Min / Max data values (pre-filled from the current curve).
- Changing the limits rebuilds an unedited preset, or stretches a hand-edited curve to the
  new range while keeping its shape.

## Colour and saving
- **Colour ramp:** any QGIS ramp (default is an ER Mapper-like pseudocolour); invert it from
  the button's menu.
- **Live update** restyles the layer as you edit. The curve, clip settings and ramp are saved
  with the layer, so they come back when you reopen the project.
- **Save style (.qml)** saves the stretch as a QGIS style for reuse.

## Export image
Choose in the export dialog (your last settings are remembered):
- **Format:** Cloud-Optimised GeoTIFF, tiled GeoTIFF, JPEG2000, PNG + world file, JPEG + world file
- **Compression:** WEBP, JPEG, ZSTD, DEFLATE, LZW or none (GeoTIFF formats)
- **Mode:** lossy or lossless where the compression supports both
- **Quality** (JPEG/WEBP 1–100), **target size %** (JPEG2000) or **compression level** (ZSTD/DEFLATE/PNG)
- **Transparency:** alpha channel (smooth edges), 1-bit internal mask, or none with a fill colour
- **Resolution:** 1–100 % of the grid, with the output size shown
- **Overviews** for fast display, and **add to map** when done

Options this QGIS's GDAL can't write are greyed out, and a note under the options explains the
trade-offs of the current choice.

## Notes
- For a sun-shaded look, duplicate the grid, style the copy as *Hillshade*, put it above
  the coloured layer and set its blending mode to *Multiply*.
- Values beyond ±1e30 and the layer's nodata value are treated as transparent.
- Works with QGIS 3.22 or later, including QGIS 4 (Qt6).
