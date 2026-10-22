# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Beau Garland
"""Build the installable plugin ZIP: dist/stretch_editor-<version>.zip

The ZIP holds the stretch_editor/ folder plus LICENSE, README.md and CHANGELOG.md, which is the
layout QGIS's "Install from ZIP" and the QGIS plugin repository expect. The build stops if the
package breaks a repository rule (https://plugins.qgis.org/publish/).
"""
import configparser
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / 'stretch_editor'
EXTRAS = ['LICENSE', 'README.md', 'CHANGELOG.md']
MAX_BYTES = 20 * 1024 * 1024
REQUIRED_METADATA = ['name', 'qgisMinimumVersion', 'description', 'about', 'version', 'author', 'email',
                     'repository', 'tracker', 'homepage']
BINARY_SUFFIXES = {'.pyc', '.pyd', '.so', '.dll', '.exe', '.dylib'}


def package_files():
    for p in sorted(PKG.rglob('*')):
        rel = p.relative_to(PKG)
        if p.is_dir() or '__pycache__' in rel.parts:
            continue
        yield p


def check(meta, files):
    problems = []
    missing = [k for k in REQUIRED_METADATA if not meta.get(k, '').strip()]
    if missing:
        problems.append(f'metadata.txt is missing: {", ".join(missing)}')
    for p in files:
        rel = p.relative_to(PKG)
        if any(part.startswith('.') or part == '__MACOSX' for part in rel.parts):
            problems.append(f'hidden file or folder: {rel}')
        if p.suffix.lower() in BINARY_SUFFIXES:
            problems.append(f'binary file: {rel}')
    for name in EXTRAS:
        if not (ROOT / name).is_file():
            problems.append(f'missing {name}')
    return problems


def main():
    parser = configparser.ConfigParser()
    parser.read(PKG / 'metadata.txt', encoding='utf-8')
    meta = parser['general']
    files = list(package_files())
    problems = check(meta, files)
    if problems:
        sys.exit('Not built:\n  ' + '\n  '.join(problems))

    out = ROOT / 'dist' / f'stretch_editor-{meta["version"]}.zip'
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
        for name in EXTRAS:
            z.write(ROOT / name, f'stretch_editor/{name}')
    size = out.stat().st_size
    if size > MAX_BYTES:
        out.unlink()
        sys.exit(f'Not built: the ZIP would be {size / 1e6:.1f} MB, over the 20 MB repository limit')
    count = len(files) + len(EXTRAS)
    print(f'{out.relative_to(ROOT)}  ({count} files, {size / 1024:.0f} KB) — passes repository checks')


if __name__ == '__main__':
    main()
