# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Build the installable plugin ZIP: dist/stretch_editor-<version>.zip

The ZIP holds the stretch_editor/ folder plus LICENSE, README.md and CHANGELOG.md, which is the
layout QGIS's "Install from ZIP" expects.
"""
import configparser
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'stretch_editor'
EXTRAS = ['LICENSE', 'README.md', 'CHANGELOG.md']


def main():
    meta = configparser.ConfigParser()
    meta.read(PKG / 'metadata.txt', encoding='utf-8')
    version = meta['general']['version']
    out = ROOT / 'dist' / f'stretch_editor-{version}.zip'
    out.parent.mkdir(exist_ok=True)
    files = sorted(p for p in PKG.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
        for name in EXTRAS:
            z.write(ROOT / name, f'stretch_editor/{name}')
    print(f'{out.relative_to(ROOT)}  ({len(files) + len(EXTRAS)} files, {out.stat().st_size / 1024:.0f} KB)')


if __name__ == '__main__':
    main()
