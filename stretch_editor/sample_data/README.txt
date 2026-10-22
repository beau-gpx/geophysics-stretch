Stretch Editor sample data
==========================

Three small synthetic grids for trying out and testing the plugin. Load them from
Raster > Stretch Editor > Load sample data, or add them to QGIS like any GeoTIFF.

  tmi_nT.tif          Total magnetic intensity, nT. Smooth anomalies from buried bodies,
                      dykes and a faulted magnetic unit, on a regional gradient.
                      Try: Hist. equalise, then Colour bar.
  tmi_1vd.tif         First vertical derivative of the TMI, nT/m. Straddles zero.
                      Try: Advanced > Mirror about centre, then Slope.
  potassium_pct.tif   Radiometric potassium, %. All positive and skewed.
                      Try: Log-linear and Log values (X).

All three are 400 x 320 cells of 50 m, float32 GeoTIFF, WGS 84 / UTM zone 54S (EPSG:32754),
nodata -99999 outside an irregular survey outline (useful for testing transparent exports).

The data are entirely synthetic: generated from random sources with a fixed seed by
scripts/make_sample_data.py in the plugin's source repository. The coordinates are arbitrary
and do not correspond to a real survey. You may use, copy and modify these files for any
purpose without restriction (CC0 1.0 public domain dedication).
