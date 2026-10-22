# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Reading raster data from QGIS layers, and small helpers for the layer being edited."""
import numpy as np
from qgis.core import Qgis, QgsMapLayerProxyModel, QgsProject

from .compat import first_attr

DUMMY_LIMIT = 1e30      # |value| above this is treated as a dummy/nodata value (e.g. ±3.4e38)

_DTYPES = [('Byte', np.uint8), ('Int8', np.int8), ('UInt16', np.uint16), ('Int16', np.int16),
           ('UInt32', np.uint32), ('Int32', np.int32), ('Float32', np.float32), ('Float64', np.float64)]


def raster_layer_filter():
    """Filter for QgsMapLayerComboBox that shows raster layers only."""
    return first_attr((Qgis, 'LayerFilter.RasterLayer'), (QgsMapLayerProxyModel, 'Filter.RasterLayer'),
                      (QgsMapLayerProxyModel, 'RasterLayer'))


def _numpy_dtype(data_type):
    for name, dtype in _DTYPES:
        for path in ('DataType.' + name, name):
            try:
                if data_type == first_attr((Qgis, path)):
                    return dtype
            except AttributeError:
                pass
    raise ValueError('Unsupported raster data type (complex or unknown).')


def read_block(provider, band, extent, width, height):
    """Read a band over extent at width x height pixels as float64, with nodata as NaN."""
    block = provider.block(band, extent, width, height)
    arr = None
    if hasattr(block, 'as_numpy'):                      # QGIS 3.34+
        try:
            a = block.as_numpy(use_masking=True)
            arr = a.astype(np.float64).filled(np.nan) if np.ma.isMaskedArray(a) else np.array(a, np.float64)
        except Exception:
            arr = None
    if arr is None:
        raw = bytes(block.data())
        arr = np.frombuffer(raw, dtype=_numpy_dtype(block.dataType())).astype(np.float64)
    arr = arr.reshape(height, width)
    if block.hasNoDataValue():
        arr[arr == block.noDataValue()] = np.nan
    if provider.sourceHasNoDataValue(band) and provider.useSourceNoDataValue(band):
        arr[arr == provider.sourceNoDataValue(band)] = np.nan
    with np.errstate(invalid='ignore'):
        arr[np.abs(arr) > DUMMY_LIMIT] = np.nan
    return arr


def sample_band(layer, band, max_size):
    """Valid values of a band, read at no more than max_size pixels on the long side."""
    w, h = layer.width(), layer.height()
    f = min(1.0, max_size / max(w, h))
    a = read_block(layer.dataProvider(), band, layer.extent(), max(1, int(w * f)), max(1, int(h * f)))
    s = a[np.isfinite(a)]
    if s.size < 2:
        raise ValueError('the band has no valid data')
    return s


def existing_stretch_range(layer, band):
    """(min, max) of the layer's current single-band stretch, or None."""
    try:
        r = layer.renderer()
        if r is None:
            return None
        if hasattr(r, 'contrastEnhancement') and r.contrastEnhancement() is not None:
            if hasattr(r, 'grayBand') and r.grayBand() != band:
                return None
            ce = r.contrastEnhancement()
            lo, hi = ce.minimumValue(), ce.maximumValue()
        elif hasattr(r, 'classificationMin'):
            if hasattr(r, 'band') and r.band() != band:
                return None
            lo, hi = r.classificationMin(), r.classificationMax()
        else:
            return None
        if lo is None or hi is None or not np.isfinite([lo, hi]).all() or not hi > lo:
            return None
        return float(lo), float(hi)
    except Exception:
        return None


def map_units(layer):
    """Abbreviated map units of the layer's CRS (e.g. 'm'), or ''."""
    try:
        from qgis.core import QgsUnitTypes
        return QgsUnitTypes.toAbbreviatedString(layer.crs().mapUnits())
    except Exception:
        return ''


def show_in_layers_panel(iface, layer):
    """Make layer the active layer: expand its groups, select it and scroll to it."""
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    parent = node.parent() if node else None
    while parent is not None:
        if hasattr(parent, 'setExpanded'):
            parent.setExpanded(True)
        parent = parent.parent()
    iface.setActiveLayer(layer)
    view = iface.layerTreeView()
    if view is not None:
        view.setCurrentLayer(layer)
        view.scrollTo(view.currentIndex())


def provider_resampling(provider, method):
    """Temporarily switch a provider's resampling ('nearest', 'bilinear', 'cubic', 'average').
    Returns (restore_function, ok); ok is False if the provider can't resample."""
    name = {'nearest': 'Nearest', 'bilinear': 'Bilinear', 'cubic': 'Cubic', 'average': 'Average'}[method]
    try:
        from qgis.core import QgsRasterDataProvider
        m = first_attr((QgsRasterDataProvider, 'ResamplingMethod.' + name), (Qgis, 'RasterResamplingMethod.' + name))
        old = (provider.isProviderResamplingEnabled(), provider.zoomedInResamplingMethod(),
               provider.zoomedOutResamplingMethod())
    except Exception:
        return (lambda: None), method == 'nearest'

    def restore():
        try:
            provider.setZoomedInResamplingMethod(old[1])
            provider.setZoomedOutResamplingMethod(old[2])
            provider.enableProviderResampling(old[0])
        except Exception:
            pass

    try:
        ok = provider.enableProviderResampling(method != 'nearest')
        provider.setZoomedInResamplingMethod(m)
        provider.setZoomedOutResamplingMethod(m)
    except Exception:
        ok = False
    return restore, bool(ok) or method == 'nearest'
