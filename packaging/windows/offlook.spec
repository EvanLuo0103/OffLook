from pathlib import Path
from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

here = Path(SPECPATH)
raw_data, raw_binaries, raw_hidden = collect_all('pypdfium2_raw')
if not any(Path(source).name.lower() == 'pdfium.dll' for source, _ in raw_binaries):
    raw_binaries.append((str(Path(find_spec('pypdfium2_raw').origin).with_name('pdfium.dll')), 'pypdfium2_raw'))
analysis = Analysis(
    [str(here / 'entry.py')],
    pathex=[str(here.parents[1] / 'src')],
    binaries=raw_binaries,
    datas=raw_data + copy_metadata('offlook'),
    hiddenimports=raw_hidden + collect_submodules('offlook') + ['win32cred', 'win32com.client'],
    excludes=['IPython', 'pytest', 'numpy', 'pandas'],
)
pyz = PYZ(analysis.pure)
gui = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='OffLook', console=False, upx=False)
cli = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='ol', console=True, upx=False)
bundle = COLLECT(gui, cli, analysis.binaries, analysis.datas, name='OffLook', upx=False)
