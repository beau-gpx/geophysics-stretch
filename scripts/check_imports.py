# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Import every plugin module against stand-in qgis / Qt / GDAL modules, without QGIS installed.

Catches syntax errors, bad relative imports, module-level errors and references to helper
functions that don't exist (e.g. after a rename). It does NOT exercise Qt or QGIS behaviour:
test in a real QGIS before releasing.

    python scripts/check_imports.py            # checks ./stretch_editor
    python scripts/check_imports.py <folder>   # checks <folder>/stretch_editor (e.g. an unzipped build)
"""
import ast
import importlib
import pathlib
import sys
import types

STUBBED = ['qgis', 'qgis.core', 'qgis.gui', 'qgis.PyQt', 'qgis.PyQt.QtCore', 'qgis.PyQt.QtGui',
           'qgis.PyQt.QtWidgets', 'qgis.PyQt.QtSvg', 'osgeo', 'osgeo.gdal']

MODULES = ['stretch_editor', 'stretch_editor.compat', 'stretch_editor.core.stretch', 'stretch_editor.core.colourbar',
           'stretch_editor.core.export', 'stretch_editor.layers', 'stretch_editor.styling', 'stretch_editor.state',
           'stretch_editor.legend', 'stretch_editor.ui.curve_widget', 'stretch_editor.ui.export_dialog',
           'stretch_editor.ui.colourbar_dialog', 'stretch_editor.ui.dock', 'stretch_editor.plugin']

# local names the code uses for the plugin's own helper modules
ALIASES = {'layers': 'stretch_editor.layers', 'styling': 'stretch_editor.styling', 'state': 'stretch_editor.state',
           'legend': 'stretch_editor.legend', 'stretch': 'stretch_editor.core.stretch',
           'st': 'stretch_editor.core.stretch', 'export': 'stretch_editor.core.export',
           'ex': 'stretch_editor.core.export', 'cb': 'stretch_editor.core.colourbar'}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return _stub_class(name)


class _Stub(metaclass=_Meta):
    """Accepts any construction, call, attribute access or | combination."""
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __getattr__(self, name):
        return _Stub()

    def __or__(self, other):
        return _Stub()


def _stub_class(name):
    return _Meta(name, (_Stub,), {})


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        cls = _stub_class(name)
        setattr(self, name, cls)
        return cls


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent)
    for name in STUBBED:
        module = _StubModule(name)
        module.__path__ = []
        sys.modules[name] = module
    sys.path.insert(0, str(root))

    for name in MODULES:
        importlib.import_module(name)
    print(f'imported {len(MODULES)} modules')

    missing = []
    for path in (root / 'stretch_editor').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in ALIASES and node.value.id in imported):
                target = sys.modules[ALIASES[node.value.id]]
                if not hasattr(target, node.attr) or isinstance(getattr(target, node.attr), _Meta):
                    missing.append(f'{path.relative_to(root)}:{node.lineno}  {node.value.id}.{node.attr}')
    if missing:
        sys.exit('references to missing helpers:\n  ' + '\n  '.join(missing))
    print('all references to plugin helper modules resolve')


if __name__ == '__main__':
    main()
