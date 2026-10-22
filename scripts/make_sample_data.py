# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Generate the synthetic sample grids in stretch_editor/sample_data/.

The grids are made up (random sources from a fixed seed), so they carry no data-licence
restrictions. Coordinates are arbitrary and do not correspond to a real survey.

Requires numpy and tifffile:  python scripts/make_sample_data.py
"""
import pathlib

import numpy as np
import tifffile

OUT = pathlib.Path(__file__).resolve().parent.parent / 'stretch_editor' / 'sample_data'
NX, NY = 400, 320               # columns, rows
CELL = 50.0                     # metres
X0, Y0 = 300000.0, 6200000.0    # top-left corner (WGS 84 / UTM zone 54S, arbitrary location)
EPSG = 32754
NODATA = -99999.0
SEED = 2026


PAD = 128                       # cells of reflected padding so FFT filters don't wrap around


def wavenumbers(shape):
    ny, nx = shape
    kx = np.fft.fftfreq(nx, CELL) * 2 * np.pi
    ky = np.fft.fftfreq(ny, CELL) * 2 * np.pi
    return np.hypot(*np.meshgrid(kx, ky))


def fft_filter(grid, response):
    """Apply a radial wavenumber filter response(k) with reflected padding."""
    padded = np.pad(grid, PAD, mode='reflect')
    out = np.real(np.fft.ifft2(np.fft.fft2(padded) * response(wavenumbers(padded.shape))))
    return out[PAD:-PAD, PAD:-PAD]


def survey_mask():
    """Irregular survey outline: a tilted block with a notch, the rest is nodata."""
    yy, xx = np.mgrid[0:NY, 0:NX].astype(float)
    u = (xx - NX / 2) * np.cos(0.25) + (yy - NY / 2) * np.sin(0.25)
    v = -(xx - NX / 2) * np.sin(0.25) + (yy - NY / 2) * np.cos(0.25)
    inside = (np.abs(u) < NX * 0.44) & (np.abs(v) < NY * 0.40)
    notch = (u > NX * 0.18) & (v < -NY * 0.12)
    return inside & ~notch


def magnetic_sources(rng):
    """Magnetisation maps paired with a source depth (m): bodies, dykes and a faulted unit."""
    yy, xx = np.mgrid[0:NY, 0:NX].astype(float)
    sources = []
    for _ in range(12):                                   # compact bodies at varied depths
        cx, cy, r = rng.uniform(0, NX), rng.uniform(0, NY), rng.uniform(3, 14)
        body = rng.uniform(0.6, 2.0) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / r ** 2)
        sources.append((body, rng.uniform(120, 500)))
    for _ in range(3):                                    # dykes
        ang, off = rng.uniform(0, np.pi), rng.uniform(-NX / 3, NX / 3)
        d = (xx - NX / 2) * np.cos(ang) + (yy - NY / 2) * np.sin(ang) - off
        sources.append((rng.uniform(0.4, 0.8) * np.exp(-(d / 1.2) ** 2), rng.uniform(150, 300)))
    edge = 1 / (1 + np.exp(-((yy - 0.35 * xx) - NY * 0.45) / 3))            # unit with a soft contact
    fault = 1 / (1 + np.exp((xx - NX * 0.7) / 2))                           # cut off by a fault
    sources.append((0.25 * edge * fault, 400.0))
    return sources


def total_magnetic_intensity(rng):
    """TMI in nT: each source's field seen from 60 m above ground, plus a regional and sensor noise."""
    anomaly = np.zeros((NY, NX))
    for m, depth in magnetic_sources(rng):
        z = 60.0 + depth
        anomaly += fft_filter(m, lambda k, z=z: k * np.exp(-k * z) * (1 - np.exp(-k * 400.0)))
    anomaly *= 380.0 / np.percentile(np.abs(anomaly - np.median(anomaly)), 99.5)
    yy, xx = np.mgrid[0:NY, 0:NX].astype(float)
    regional = 57650.0 + 0.35 * xx - 0.2 * yy
    return regional + anomaly + rng.normal(0, 0.15, (NY, NX))


def vertical_derivative(tmi):
    """First vertical derivative (nT/m) by FFT, with a light low-pass to tame noise."""
    return fft_filter(tmi - tmi.mean(), lambda k: k * np.exp(-k * 25.0))


def potassium(rng):
    """Radiometric potassium (%): positive and skewed, with a few K-rich units and noise."""
    yy, xx = np.mgrid[0:NY, 0:NX].astype(float)
    base = fft_filter(rng.normal(size=(NY, NX)), lambda k: np.exp(-k * 400.0))
    base = (base - base.mean()) / base.std()
    k_pct = 0.8 * np.exp(0.35 * base)
    for _ in range(5):
        cx, cy, r = rng.uniform(0, NX), rng.uniform(0, NY), rng.uniform(15, 50)
        k_pct += rng.uniform(1.0, 3.0) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / r ** 2)
    k_pct += rng.normal(0, 0.06, (NY, NX))
    return np.clip(k_pct, 0.05, None)


def write_geotiff(path, data, mask, description):
    """Float32 GeoTIFF with georeferencing, a nodata value and DEFLATE compression."""
    arr = np.where(mask, data, NODATA).astype(np.float32)
    geokeys = [1, 1, 0, 3,
               1024, 0, 1, 1,          # GTModelType: projected
               1025, 0, 1, 1,          # GTRasterType: pixel is area
               3072, 0, 1, EPSG]       # ProjectedCSType
    extratags = [
        (33550, 'd', 3, (CELL, CELL, 0.0), True),                 # ModelPixelScale
        (33922, 'd', 6, (0.0, 0.0, 0.0, X0, Y0, 0.0), True),     # ModelTiepoint
        (34735, 'H', len(geokeys), geokeys, True),                # GeoKeyDirectory
        (42113, 's', 0, f'{NODATA:g}', True),                     # GDAL_NODATA
    ]
    tifffile.imwrite(path, arr, compression='adobe_deflate', description=description,
                     extratags=extratags, metadata=None)
    return arr


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    mask = survey_mask()
    tmi = total_magnetic_intensity(rng)
    grids = {
        'tmi_nT.tif': (tmi, 'Synthetic total magnetic intensity (nT)'),
        'tmi_1vd.tif': (vertical_derivative(tmi), 'Synthetic first vertical derivative of TMI (nT/m)'),
        'potassium_pct.tif': (potassium(rng), 'Synthetic radiometric potassium (%)'),
    }
    for name, (data, desc) in grids.items():
        arr = write_geotiff(OUT / name, data, mask, desc)
        v = arr[arr != NODATA]
        size = (OUT / name).stat().st_size / 1024
        print(f'{name:18s} {size:6.0f} KB  min {v.min():.5g}  median {np.median(v):.5g}  max {v.max():.5g}')


if __name__ == '__main__':
    main()
