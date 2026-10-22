# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Tests for the pure-Python parts of the plugin (no QGIS needed).

Run from the repository root:  python -m unittest discover -s tests
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stretch_editor.core import colourbar as cb  # noqa: E402
from stretch_editor.core import export as ex  # noqa: E402
from stretch_editor.core import stretch as st  # noqa: E402


def lognormal(n=100_000, seed=0):
    return np.random.default_rng(seed).lognormal(3, 1, n)


def signed_1vd(seed=0):
    rng = np.random.default_rng(seed)
    return np.concatenate([rng.laplace(0, 0.002, 200_000), rng.exponential(0.006, 30_000)])


class TestClipAndPresets(unittest.TestCase):
    def setUp(self):
        self.d = lognormal()

    def test_percent_clip_defaults_to_min_max(self):
        self.assertEqual(st.percent_clip(self.d), st.data_range(self.d))

    def test_percent_clip_matches_percentiles_and_accepts_swapped_limits(self):
        expected = tuple(np.percentile(self.d, [5, 80]))
        np.testing.assert_allclose(st.percent_clip(self.d, 5, 80), expected)
        np.testing.assert_allclose(st.percent_clip(self.d, 80, 5), expected)

    def test_presets_have_requested_points_and_span_the_clip(self):
        for kind, fn in st.PRESETS.items():
            for n in (2, 9, 32):
                nodes = fn(self.d, 10, 80, n)
                self.assertEqual(len(nodes), n, kind)
                self.assertAlmostEqual(nodes[0][0], 10)
                self.assertAlmostEqual(nodes[-1][0], 80)
                self.assertEqual((nodes[0][1], nodes[-1][1]), (0.0, 1.0))

    def test_histogram_equalise_gives_flat_output(self):
        nodes = st.preset_histeq(self.d, 10, 80, 33)
        inside = self.d[(self.d >= 10) & (self.d <= 80)]
        counts, _ = np.histogram(st.evaluate(nodes, inside), 5, (0, 1))
        self.assertLess(counts.max() / counts.min(), 1.05)

    def test_sanitize_sorts_clamps_and_separates(self):
        nodes = st.sanitize([[5, 2.0], [1, -1.0], [5, 0.5]])
        xs = [x for x, _ in nodes]
        self.assertTrue(all(b > a for a, b in zip(xs, xs[1:])))
        self.assertEqual(nodes[0][1], 0.0)
        self.assertTrue(all(0 <= y <= 1 for _, y in nodes))


class TestCurveOperations(unittest.TestCase):
    curve = [[0, 0], [20, 0.8], [50, 0.85], [100, 1]]

    def test_resample_up_keeps_shape_exactly(self):
        x = np.linspace(0, 100, 2001)
        for n in (4, 12, 40):
            r = st.resample(self.curve, n)
            self.assertEqual(len(r), n)
            np.testing.assert_allclose(st.evaluate(r, x), st.evaluate(self.curve, x), atol=1e-12)

    def test_resample_down_keeps_the_bend(self):
        r = st.resample(self.curve, 3)
        self.assertEqual(len(r), 3)
        self.assertEqual(r[1][0], 20)

    def test_rescale_moves_ends_and_keeps_shape(self):
        r = st.rescale(self.curve, 10, 30)
        self.assertEqual([x for x, _ in r], [10, 14, 20, 30])
        self.assertEqual([y for _, y in r], [y for _, y in self.curve])

    def test_fit_curve_view_is_exact(self):
        self.assertEqual(st.fit_curve_view([[12.5, 0], [87.25, 1]]), (12.5, 87.25))


class TestMirror(unittest.TestCase):
    def setUp(self):
        self.d = signed_1vd()
        self.r = st.mirror_radius(self.d, 0.0, 99)

    def test_symmetric_presets(self):
        for kind in st.PRESETS:
            for n in (2, 32, 33, 64):
                nodes = st.symmetric_preset(kind, self.d, 0.0, self.r, n)
                self.assertTrue(st.is_symmetric(nodes, 0.0), kind)
                self.assertEqual(len(nodes) % 2, 1)
                self.assertGreaterEqual(len(nodes), n)
                self.assertEqual(float(st.evaluate(nodes, [0.0])[0]), 0.5)

    def test_equal_magnitudes_get_mirrored_outputs(self):
        nodes = st.symmetric_preset('histeq', self.d, 0.0, self.r, 33)
        for v in (0.001, 0.004, 0.01):
            a, b = st.evaluate(nodes, [v, -v])
            self.assertAlmostEqual(a + b, 1.0, places=12)

    def test_mirror_from_either_side(self):
        cur = [[-5, 0], [-1, 0.3], [0, 0.5], [2, 0.9], [5, 1]]
        np.testing.assert_allclose(st.mirror(cur, 0, 'pos'), [[-5, 0.0], [-2, 0.1], [0, 0.5], [2, 0.9], [5, 1.0]])
        np.testing.assert_allclose(st.mirror(cur, 0, 'neg'), [[-5, 0.0], [-1, 0.3], [0, 0.5], [1, 0.7], [5, 1.0]])
        self.assertIsNone(st.mirror([[1, 0], [5, 1]], 0, 'neg'))

    def test_off_zero_centre(self):
        nodes = st.symmetric_preset('linear', self.d + 100, 100.0, 0.5, 3)
        self.assertTrue(st.is_symmetric(nodes, 100.0))

    def test_reslope_round_trip_and_direction(self):
        nodes = st.symmetric_preset('linear', self.d, 0.0, 0.01, 33)
        steeper = st.reslope(nodes, 1 / 2)
        self.assertGreater(st.evaluate(steeper, [0.001])[0], st.evaluate(nodes, [0.001])[0])
        back = st.reslope(steeper, 2)
        np.testing.assert_allclose([y for _, y in back], [y for _, y in nodes], atol=1e-12)
        self.assertTrue(st.is_symmetric(steeper, 0.0))


class TestLogAxis(unittest.TestCase):
    def test_round_trip(self):
        for data in (lognormal(), signed_1vd()):
            axis = st.LogAxis(data)
            v = np.array([data.min(), np.median(data), data.max()])
            np.testing.assert_allclose(axis.inv(axis.fwd(v)), v, rtol=1e-12)

    def test_positive_vs_symmetric(self):
        self.assertTrue(st.LogAxis(lognormal()).positive)
        self.assertFalse(st.LogAxis(signed_1vd()).positive)


class TestColourBar(unittest.TestCase):
    def test_nice_ticks(self):
        self.assertEqual(cb.nice_ticks(-123.4, 456.7, 6), [-100, 0.0, 100, 200, 300, 400])
        self.assertEqual(cb.nice_ticks(-3.2, 3.2, 7), [-3, -2, -1, 0.0, 1, 2, 3])

    def test_evenly_spaced_labels_follow_the_data_for_histeq(self):
        d = lognormal()
        lo, hi = st.percent_clip(d, 1, 99)
        info = cb.bar_ticks(st.preset_histeq(d, lo, hi, 32), 6, 'colour')
        values = [v for _, v in info['ticks']]
        expected = np.percentile(d[(d >= lo) & (d <= hi)], [0, 20, 40, 60, 80, 100])
        np.testing.assert_allclose(values, expected, rtol=0.02)

    def test_inverted_and_non_monotonic_curves(self):
        info = cb.bar_ticks([[0, 1], [10, 0.5], [20, 0]], 3, 'colour')
        self.assertEqual([v for _, v in info['ticks']], [20.0, 10.0, 0.0])
        self.assertEqual(cb.bar_ticks([[0, 0], [5, 1], [10, 0.2]], 4, 'colour')['mode'], 'value')

    def test_labels_and_settings(self):
        self.assertEqual(cb.labels([(0, -0.0001), (1, 1.0)], 2), ['0', '1.00'])
        s = cb.normalise({'fmt': 'gif', 'ticks': 99})
        self.assertEqual((s['fmt'], s['ticks']), ('png', 30))


class TestExportOptions(unittest.TestCase):
    def test_defaults_open_on_cell_size(self):
        self.assertEqual(ex.normalise({})['res_mode'], 'cell')

    def test_jpeg_cannot_have_alpha(self):
        s = ex.normalise({'format': 'COG', 'compression': 'JPEG', 'transparency': 'alpha'})
        self.assertEqual(s['transparency'], 'mask')
        opts, _ = ex.translate_options(s)
        self.assertIn('-mask', opts)

    def test_webp_lossless_and_gtiff_overviews(self):
        opts, _ = ex.translate_options({'format': 'COG', 'compression': 'WEBP', 'lossless': True})
        self.assertIn('QUALITY=100', opts)
        _, overviews = ex.translate_options({'format': 'GTiff', 'compression': 'ZSTD', 'overviews': True})
        self.assertTrue(overviews)

    def test_compute_grid_covers_the_extent(self):
        for s in ({'res_mode': 'scale', 'scale': 250}, {'res_mode': 'cell', 'cell': 33.0}):
            ow, oh, px, py = ex.compute_grid(ex.normalise(s), 1000, 800, 50_000.0, 40_000.0)
            self.assertGreaterEqual(ow * px, 50_000.0 - 1e-6)
            self.assertGreaterEqual(oh * py, 40_000.0 - 1e-6)

    def test_apply_lut_makes_nodata_transparent(self):
        lut = np.zeros((1024, 4), np.uint8)
        lut[:, 3] = 255
        rgba = st.apply_lut(np.array([[np.nan, 50.0]]), [[0, 0], [100, 1]], lut)
        self.assertEqual(rgba[0, 0, 3], 0)
        self.assertEqual(rgba[0, 1, 3], 255)


if __name__ == '__main__':
    unittest.main()
