# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Tests for core.ternary (no QGIS needed; the VRT round trip needs GDAL and is skipped without it)."""
import os
import pathlib
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from stretch_editor.core import ternary as tn  # noqa: E402

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / 'stretch_editor' / 'sample_data'

try:
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:
    gdal = None


def _lut_pairs(text):
    return [tuple(float(v) for v in p.split(':')) for p in text.split(',')]


class TestTernary(unittest.TestCase):
    def test_guess_channels(self):
        names = ['TMI (nT)', 'eTh_ppm', 'Potassium %', 'U ppm', 'DEM']
        self.assertEqual(tn.guess_channels(names), [2, 1, 3])
        self.assertEqual(tn.guess_channels(['K', 'Th', 'U']), [0, 1, 2])
        self.assertEqual(tn.guess_channels(['tmi', 'dem']), [None, None, None])
        self.assertEqual(tn.guess_channels(['survey_k_pct', 'survey_th_ppm', 'survey_u_ppm']), [0, 1, 2])

    def test_common_grid_identical(self):
        g = {'gt': (100.0, 25.0, 0, 5000.0, 0, -25.0), 'w': 40, 'h': 20}
        gt, w, h, rects = tn.common_grid([g, g, g])
        self.assertEqual((gt, w, h), ((100.0, 25.0, 0.0, 5000.0, 0.0, -25.0), 40, 20))
        self.assertEqual(rects[0], (0.0, 0.0, 40.0, 20.0))

    def test_common_grid_union_and_finest_cell(self):
        a = {'gt': (0.0, 50.0, 0, 1000.0, 0, -50.0), 'w': 10, 'h': 10}      # 0..500 x 500..1000
        b = {'gt': (250.0, 25.0, 0, 1250.0, 0, -25.0), 'w': 20, 'h': 20}    # 250..750 x 750..1250
        gt, w, h, rects = tn.common_grid([a, b, a])
        self.assertEqual(gt, (0.0, 25.0, 0.0, 1250.0, 0.0, -25.0))
        self.assertEqual((w, h), (30, 30))
        self.assertEqual(rects[0], (0.0, 10.0, 20.0, 20.0))
        self.assertEqual(rects[1], (10.0, 0.0, 20.0, 20.0))

    def test_common_grid_rejects_rotation(self):
        with self.assertRaises(ValueError):
            tn.common_grid([{'gt': (0, 1, 0.1, 0, 0, -1), 'w': 1, 'h': 1}])

    def test_lut_maps_curve_to_1_255_and_dummies_to_0(self):
        pairs = _lut_pairs(tn.lut_text([[0.0, 0.0], [5.0, 0.25], [10.0, 1.0]]))
        xs = [x for x, _ in pairs]
        self.assertEqual(xs, sorted(xs))
        inner = [(x, y) for x, y in pairs if abs(x) < 1e29]
        self.assertEqual(inner, [(0.0, 1.0), (5.0, 64.5), (10.0, 255.0)])
        self.assertEqual(pairs[0][1], 0.0)                  # below -1e30: transparent
        self.assertEqual(pairs[-1][1], 0.0)                 # above +1e30: transparent

    def test_lut_invert(self):
        inner = [(x, y) for x, y in _lut_pairs(tn.lut_text([[0, 0], [10, 1]], invert=True)) if abs(x) < 1e29]
        self.assertEqual(inner, [(0.0, 255.0), (10.0, 1.0)])

    def test_settings_round_trip_through_vrt_text(self):
        src = {'path': '/data/k.tif', 'band': 1, 'w': 4, 'h': 3, 'nodata': -99999.0, 'wkt': 'LOCAL_CS["x"]',
               'name': 'K & <pct>'}
        target = tn.common_grid([{'gt': (0.0, 1.0, 0, 3.0, 0, -1.0), 'w': 4, 'h': 3}] * 3)
        settings = {'channels': [{'name': 'K & <pct>'}, {}, {}], 'invert': False}
        text = tn.vrt_xml(target, [src] * 3, [[[0, 0], [1, 1]]] * 3, settings=settings)
        self.assertEqual(tn.read_settings(text), settings)
        self.assertIsNone(tn.read_settings('<VRTDataset/>'))
        self.assertIsNone(tn.read_settings('not xml'))

    def test_render_nodata_in_any_channel_is_transparent(self):
        v = [np.array([[0.0, 5.0, np.nan]]), np.array([[0.0, 5.0, 1.0]]), np.array([[10.0, np.nan, 1.0]])]
        curve = [[0.0, 0.0], [10.0, 1.0]]
        rgba = tn.render(v, [curve] * 3)
        self.assertEqual(rgba[0, 0].tolist(), [0, 0, 255, 255])
        self.assertEqual(rgba[0, 1, 3], 0)
        self.assertEqual(rgba[0, 2, 3], 0)
        self.assertEqual(tn.render(v, [curve] * 3, invert=True)[0, 0].tolist(), [255, 255, 0, 255])

    def test_channel_colours(self):
        c = tn.channel_colours(1, n=3)
        self.assertEqual(c.tolist(), [[0, 0, 0], [0, 128, 0], [0, 255, 0]])
        self.assertEqual(tn.channel_colours(0, invert=True, n=2).tolist(), [[255, 255, 255], [0, 255, 255]])

    def test_triangle_corners_and_centre(self):
        img, (top, bl, br) = tn.triangle(201)
        def at(p, dx=0, dy=0):
            return img[int(p[1] + dy), int(p[0] + dx)].tolist()
        for px, want in ((at(top, dy=4), 0), (at(bl, dx=4, dy=-2), 1), (at(br, dx=-4, dy=-2), 2)):
            self.assertEqual(px[want], 255)                     # pure channel colour at its corner
            self.assertTrue(all(v < 20 for k, v in enumerate(px[:3]) if k != want))
        cy = (top[1] + 2 * bl[1]) / 3                      # centroid: white
        self.assertTrue(all(v > 245 for v in img[int(cy), 100, :3]))
        self.assertEqual(img[0, 0, 3], 0)                  # outside the triangle: transparent

    @unittest.skipIf(gdal is None, 'GDAL not installed')
    def test_vrt_opens_in_gdal_with_curves_and_nodata(self):
        paths = [str(SAMPLES / n) for n in ('potassium_pct.tif', 'tmi_nT.tif', 'tmi_1vd.tif')]
        srcs, grids, data = [], [], []
        for p in paths:
            ds = gdal.Open(p)
            b = ds.GetRasterBand(1)
            a = b.ReadAsArray().astype(float)
            a[a == b.GetNoDataValue()] = np.nan
            data.append(a)
            grids.append({'gt': ds.GetGeoTransform(), 'w': ds.RasterXSize, 'h': ds.RasterYSize})
            srcs.append({'path': p, 'band': 1, 'w': ds.RasterXSize, 'h': ds.RasterYSize,
                         'nodata': b.GetNoDataValue(), 'wkt': ds.GetProjection()})
        curves = [[[float(np.nanpercentile(a, 2)), 0.0], [float(np.nanpercentile(a, 98)), 1.0]] for a in data]
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'ternary.vrt')
            with open(out, 'w') as f:
                f.write(tn.vrt_xml(tn.common_grid(grids), srcs, curves, settings={'channels': [{}, {}, {}]},
                                   vrt_path=out))
            ds = gdal.Open(out)
            self.assertEqual((ds.RasterCount, ds.RasterXSize, ds.RasterYSize), (3, 400, 320))
            self.assertIn(tn.METADATA_KEY, ds.GetMetadata())
            vrt = ds.ReadAsArray()
        valid = np.isfinite(data[0]) & np.isfinite(data[1]) & np.isfinite(data[2])
        self.assertTrue((vrt[:, ~valid] == 0).all())                    # nodata -> 0 (transparent)
        self.assertTrue((vrt[:, valid] >= 1).all())
        want = tn.render(data, curves)[..., :3].transpose(2, 0, 1).astype(int)
        diff = np.abs(vrt[:, valid].astype(int) - (1 + want[:, valid] * 254 / 255))
        self.assertLessEqual(float(diff.max()), 1.0)                    # same curves as the export


if __name__ == '__main__':
    unittest.main()
