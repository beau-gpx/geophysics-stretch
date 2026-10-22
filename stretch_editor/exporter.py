"""Export the stretched grid as an RGB(A) image with GDAL (no QGIS imports)."""
import os
import tempfile

import numpy as np

from . import stretch

# key: label, extension, GDAL driver, compressions, transparency modes, overviews option
FORMATS = {
    'COG':   dict(label='Cloud-Optimised GeoTIFF (.tif)', ext='.tif', driver='COG',
                  comps=['WEBP', 'JPEG', 'ZSTD', 'DEFLATE', 'LZW', 'NONE'],
                  transp=['alpha', 'mask', 'none'], overviews=True),
    'GTiff': dict(label='GeoTIFF, tiled (.tif)', ext='.tif', driver='GTiff',
                  comps=['WEBP', 'JPEG', 'ZSTD', 'DEFLATE', 'LZW', 'NONE'],
                  transp=['alpha', 'mask', 'none'], overviews=True),
    'JP2':   dict(label='JPEG2000 (.jp2)', ext='.jp2', driver='JP2OpenJPEG',
                  comps=['JPEG2000'], transp=['alpha', 'none'], overviews=False),
    'PNG':   dict(label='PNG + world file (.png)', ext='.png', driver='PNG',
                  comps=['DEFLATE'], transp=['alpha', 'none'], overviews=False),
    'JPEG':  dict(label='JPEG + world file (.jpg)', ext='.jpg', driver='JPEG',
                  comps=['JPEG'], transp=['none'], overviews=False),
}

# lossy/lossless capability and compression-level range (None = no level)
COMPS = {
    'WEBP':     dict(label='WEBP',     lossy=True,  lossless=True,  level=None),
    'JPEG':     dict(label='JPEG',     lossy=True,  lossless=False, level=None),
    'JPEG2000': dict(label='JPEG2000 wavelet', lossy=True, lossless=True, level=None),
    'ZSTD':     dict(label='ZSTD',     lossy=False, lossless=True,  level=(1, 22, 9)),
    'DEFLATE':  dict(label='DEFLATE',  lossy=False, lossless=True,  level=(1, 9, 6)),
    'LZW':      dict(label='LZW',      lossy=False, lossless=True,  level=None),
    'NONE':     dict(label='None (uncompressed)', lossy=False, lossless=True, level=None),
}

TRANSP = {'alpha': 'Alpha channel (smooth edges)',
          'mask': '1-bit internal mask',
          'none': 'None — fill with background colour'}

RESAMPLING = {'nearest': 'Nearest neighbour', 'bilinear': 'Bilinear', 'cubic': 'Cubic',
              'average': 'Average (for coarser cells)'}

DEFAULTS = dict(format='COG', compression='WEBP', lossless=False, quality=90, level=6,
                jp2_size=10, transparency='alpha', bg=[255, 255, 255],
                res_mode='cell', scale=100, cell=0.0, resampling='bilinear',
                overviews=True, add_to_map=True)

MAX_SCALE = 1000


def compute_grid(s, w, h, ext_w, ext_h):
    """Output size and pixel size for the settings.
    Cell-size mode keeps the exact cell and extends the extent to whole cells."""
    if s.get('res_mode') == 'cell' and s.get('cell', 0) > 0:
        c = float(s['cell'])
        ow = max(1, int(np.ceil(ext_w / c - 1e-6)))
        oh = max(1, int(np.ceil(ext_h / c - 1e-6)))
        return ow, oh, c, c
    f = s.get('scale', 100) / 100.0
    ow, oh = max(1, round(w * f)), max(1, round(h * f))
    return ow, oh, ext_w / ow, ext_h / oh


def allowed_transparency(fmt, comp):
    t = list(FORMATS[fmt]['transp'])
    if comp == 'JPEG' and 'alpha' in t:
        t.remove('alpha')          # JPEG can't store an alpha band
    return t


def normalise(s):
    """Fill defaults and force a consistent combination of settings."""
    s = {**DEFAULTS, **(s or {})}
    if s['format'] not in FORMATS:
        s['format'] = 'COG'
    f = FORMATS[s['format']]
    if s['compression'] not in f['comps']:
        s['compression'] = f['comps'][0]
    c = COMPS[s['compression']]
    if not c['lossy']:
        s['lossless'] = True
    if not c['lossless']:
        s['lossless'] = False
    if s['transparency'] not in allowed_transparency(s['format'], s['compression']):
        s['transparency'] = allowed_transparency(s['format'], s['compression'])[0]
    if c['level']:
        lo, hi, _ = c['level']
        s['level'] = min(hi, max(lo, int(s['level'])))
    s['quality'] = min(100, max(1, int(s['quality'])))
    s['jp2_size'] = min(100, max(1, int(s['jp2_size'])))
    s['scale'] = min(MAX_SCALE, max(1, int(s['scale'])))
    if s['res_mode'] not in ('scale', 'cell'):
        s['res_mode'] = 'cell'
    if s['resampling'] not in RESAMPLING:
        s['resampling'] = 'bilinear'
    s['cell'] = max(0.0, float(s.get('cell') or 0.0))
    return s


def n_bands(s):
    return 3 if s['transparency'] == 'none' else 4


def translate_options(s):
    """gdal_translate arguments for the settings. Returns (options, build_overviews)."""
    s = normalise(s)
    fmt, c, q, lvl = s['format'], s['compression'], s['quality'], s['level']
    o = ['-of', FORMATS[fmt]['driver']]

    def co(*kv):
        for x in kv:
            o.extend(['-co', x])

    post_ovr = False
    if fmt == 'COG':
        co('BIGTIFF=IF_SAFER', f'COMPRESS={c}', 'OVERVIEWS=' + ('AUTO' if s['overviews'] else 'NONE'))
        if c == 'WEBP':
            co('QUALITY=100' if s['lossless'] else f'QUALITY={q}')
        elif c == 'JPEG':
            co(f'QUALITY={q}')
        elif c in ('DEFLATE', 'ZSTD'):
            co(f'LEVEL={lvl}', 'PREDICTOR=YES')
        elif c == 'LZW':
            co('PREDICTOR=YES')
    elif fmt == 'GTiff':
        co('TILED=YES', 'BIGTIFF=IF_SAFER', f'COMPRESS={c}')
        if c == 'WEBP':
            co('WEBP_LOSSLESS=TRUE' if s['lossless'] else f'WEBP_LEVEL={q}')
        elif c == 'JPEG':
            co(f'JPEG_QUALITY={q}', 'PHOTOMETRIC=YCBCR')
        elif c == 'DEFLATE':
            co(f'ZLEVEL={lvl}', 'PREDICTOR=2')
        elif c == 'ZSTD':
            co(f'ZSTD_LEVEL={lvl}', 'PREDICTOR=2')
        elif c == 'LZW':
            co('PREDICTOR=2')
        if s['transparency'] == 'alpha':
            co('ALPHA=YES')
        post_ovr = bool(s['overviews'])
    elif fmt == 'JP2':
        if s['lossless']:
            co('REVERSIBLE=YES', 'QUALITY=100')
        else:
            co(f"QUALITY={s['jp2_size']}")
        if s['transparency'] == 'alpha':
            co('ALPHA=YES')
    elif fmt == 'PNG':
        co('WORLDFILE=YES', f'ZLEVEL={lvl}')
    elif fmt == 'JPEG':
        co('WORLDFILE=YES', f'QUALITY={q}')

    if s['transparency'] == 'mask':
        o += ['-b', '1', '-b', '2', '-b', '3', '-mask', '4']
    return o, post_ovr


def gdal_capabilities():
    """Which compressions/formats this QGIS's GDAL can write."""
    try:
        from osgeo import gdal
    except ImportError:
        return set(), set()
    comps = set()
    drv = gdal.GetDriverByName('GTiff')
    opts = (drv.GetMetadataItem('DMD_CREATIONOPTIONLIST') or '') if drv else ''
    for c in COMPS:
        if c in ('JPEG2000',) or f'<Value>{c}</Value>' in opts or c == 'NONE':
            comps.add(c)
    fmts = {k for k, f in FORMATS.items() if gdal.GetDriverByName(f['driver']) is not None}
    return comps, fmts


def run_export(read_strip, ow, oh, geotransform, wkt, nodes, lut_rgba, settings, out, progress=None):
    """read_strip(row0, nrows) -> float array (nrows, ow) with NaN for nodata.
    progress(fraction, message) -> False to cancel. Returns True if written."""
    from osgeo import gdal
    gdal.UseExceptions()
    s = normalise(settings)
    nb = n_bands(s)
    opts, post_ovr = translate_options(s)
    fd, tmp = tempfile.mkstemp(suffix='.tif')
    os.close(fd)
    try:
        ds = gdal.GetDriverByName('GTiff').Create(
            tmp, ow, oh, nb, gdal.GDT_Byte, ['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
        ds.SetGeoTransform(geotransform)
        if wkt:
            ds.SetProjection(wkt)
        ci = [gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand, gdal.GCI_AlphaBand]
        for b in range(nb):
            ds.GetRasterBand(b + 1).SetColorInterpretation(ci[b])
        strip = 512
        for r0 in range(0, oh, strip):
            n = min(strip, oh - r0)
            rgba = stretch.apply_lut(read_strip(r0, n), nodes, lut_rgba)
            data = rgba if nb == 4 else stretch.flatten(rgba, s['bg'])
            for b in range(nb):
                ds.GetRasterBand(b + 1).WriteArray(np.ascontiguousarray(data[:, :, b]), 0, r0)
            if progress and progress(0.8 * (r0 + n) / oh, 'Rendering…') is False:
                ds = None
                return False
        ds.FlushCache()
        ds = None

        if progress:
            progress(0.85, 'Compressing…')
        gdal.Translate(out, tmp, options=opts)

        if post_ovr:
            if progress:
                progress(0.92, 'Building overviews…')
            _build_overviews(out, ow, oh, s)
        if progress:
            progress(1.0, 'Done')
        return True
    finally:
        for f in (tmp, tmp + '.aux.xml'):
            try:
                os.remove(f)
            except OSError:
                pass


def _build_overviews(path, ow, oh, s):
    from osgeo import gdal
    levels, f = [], 2
    while max(ow, oh) / f >= 256:
        levels.append(f)
        f *= 2
    if not levels:
        return
    c = s['compression']
    cfg = {'COMPRESS_OVERVIEW': c}
    if c == 'JPEG':
        cfg.update(JPEG_QUALITY_OVERVIEW=str(s['quality']), PHOTOMETRIC_OVERVIEW='YCBCR')
    elif c == 'WEBP':
        cfg.update(WEBP_LEVEL_OVERVIEW=str(s['quality']))
    elif c in ('DEFLATE', 'ZSTD', 'LZW'):
        cfg.update(PREDICTOR_OVERVIEW='2')
    old = {k: gdal.GetConfigOption(k) for k in cfg}
    try:
        for k, v in cfg.items():
            gdal.SetConfigOption(k, v)
        ds = gdal.Open(path, gdal.GA_Update)
        ds.BuildOverviews('AVERAGE', levels)
        ds = None
    finally:
        for k, v in old.items():
            gdal.SetConfigOption(k, v)
