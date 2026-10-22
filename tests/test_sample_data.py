# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Checks on the bundled sample grids. The value checks need tifffile and are skipped without it."""
import pathlib
import unittest

import numpy as np

DATA = pathlib.Path(__file__).resolve().parent.parent / 'stretch_editor' / 'sample_data'
GRIDS = ['tmi_nT.tif', 'tmi_1vd.tif', 'potassium_pct.tif']

try:
    import tifffile
except ImportError:
    tifffile = None


class TestSampleData(unittest.TestCase):
    def test_files_present_and_small(self):
        for name in GRIDS:
            path = DATA / name
            self.assertTrue(path.is_file(), name)
            self.assertLess(path.stat().st_size, 1_000_000, name)
        self.assertTrue((DATA / 'README.txt').is_file())

    @unittest.skipIf(tifffile is None, 'tifffile not installed')
    def test_georeferenced_with_nodata_collar(self):
        for name in GRIDS:
            with tifffile.TiffFile(DATA / name) as tif:
                page = tif.pages[0]
                self.assertTrue(tif.is_geotiff, name)
                self.assertEqual(page.tags[34735].value[-1], 32754)        # EPSG code
                nodata = float(page.tags[42113].value)
                arr = page.asarray()
            self.assertEqual(arr.dtype, np.float32)
            valid = arr != nodata
            self.assertTrue(0.4 < valid.mean() < 0.9, name)                  # collar present
            self.assertTrue(np.isfinite(arr[valid]).all(), name)

    @unittest.skipIf(tifffile is None, 'tifffile not installed')
    def test_value_character(self):
        def values(name):
            arr = tifffile.imread(DATA / name)
            return arr[arr != -99999]
        tmi, vd, k = values('tmi_nT.tif'), values('tmi_1vd.tif'), values('potassium_pct.tif')
        self.assertTrue(50_000 < np.median(tmi) < 65_000)
        self.assertLess(vd.min(), 0)
        self.assertGreater(vd.max(), 0)
        self.assertGreater(k.min(), 0)
        self.assertGreater(np.mean(k), np.median(k))                         # positively skewed


if __name__ == '__main__':
    unittest.main()
