"""Fail release gates on mismatched local or indexed distribution artifacts."""
import argparse
import configparser
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import tarfile
import time
import tomllib
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
NAME = PROJECT['name']
VERSION = PROJECT['version']
WHEEL = f'{NAME}-{VERSION}-py3-none-any.whl'
SDIST = f'{NAME}-{VERSION}.tar.gz'


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def local_files(directory: Path) -> dict[str, str]:
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    require(set(files) == {WHEEL, SDIST}, 'Expected only the versioned OffLook wheel and sdist')
    return files


def inspect_distribution(directory: Path) -> None:
    local_files(directory)
    prefix = f'{NAME}-{VERSION}.dist-info/'
    with ZipFile(directory / WHEEL) as wheel:
        names = wheel.namelist()
        require(all(n.startswith(('offlook/', prefix)) and '/__pycache__/' not in n for n in names),
                'Wheel contains non-package files')
        require(not any(n.lower().endswith(('.exe', '.tmp', '/config.json')) for n in names),
                'Wheel contains executables or local configuration')
        require(prefix + 'licenses/LICENSE' in names, 'Wheel is missing MIT license')
        metadata = BytesParser().parsebytes(wheel.read(prefix + 'METADATA'))
        require(metadata['Name'] == NAME and metadata['Version'] == VERSION and
                SpecifierSet(metadata['Requires-Python']) == SpecifierSet(PROJECT['requires-python']) and
                metadata['License-Expression'] == 'MIT',
                'Incorrect package identity, Python requirement or license')
        require(metadata['Description-Content-Type'] == 'text/markdown' and
                metadata.get_payload(decode=True).decode('utf-8').splitlines() ==
                (ROOT / PROJECT['readme']).read_text(encoding='utf-8').splitlines(),
                'Wheel does not contain the expected PyPI Markdown description')
        require('office' in metadata.get_all('Provides-Extra', []), 'Wheel is missing the office extra')
        found = {Requirement(req) for req in metadata.get_all('Requires-Dist', [])}
        base = {Requirement(req) for req in (ROOT / 'requirements.txt').read_text().splitlines()
                if req.strip() and not req.lstrip().startswith('#')}
        require({req for req in found if not req.marker or 'extra' not in str(req.marker)} == base,
                'Base dependency metadata differs from requirements.txt')
        office = {Requirement(req) for req in PROJECT['optional-dependencies']['office']}
        for expected in office:
            require(any(req.name == expected.name and req.specifier == expected.specifier and req.marker
                        and req.marker.evaluate({'extra': 'office', 'sys_platform': 'win32'})
                        and not req.marker.evaluate({'extra': '', 'sys_platform': 'win32'})
                        and bool(req.marker.evaluate({'extra': 'office', 'sys_platform': 'linux'})) ==
                        (not expected.marker or expected.marker.evaluate({'sys_platform': 'linux'}))
                        for req in found), f'Incorrect office dependency metadata: {expected.name}')
        entries = configparser.ConfigParser()
        entries.read_string(wheel.read(prefix + 'entry_points.txt').decode('utf-8'))
        require(dict(entries['console_scripts']) == PROJECT['scripts'], 'Console entry points do not match pyproject')
    with tarfile.open(directory / SDIST, 'r:gz') as source:
        members = {entry.name.partition('/')[2] for entry in source.getmembers()}
        require({'pyproject.toml', 'requirements.txt', PROJECT['readme'], 'README.md', 'README.zh-TW.md',
                 'LICENSE', 'docs/getting-started.md', 'docs/api.md'} <= members,
                'Source distribution is missing build inputs or documentation')
        require(not any(n.startswith(('qa/', 'tests/', '.github/', 'packaging/', 'dist/')) or
                        n.lower().endswith(('.exe', '.tmp', '/config.json')) for n in members),
                'Source distribution includes tests, installer, workflows or local files')


def verify_index(directory: Path, host: str) -> None:
    wanted = local_files(directory)
    for attempt in range(12):
        try:
            with urlopen(f'https://{host}/pypi/{NAME}/{VERSION}/json', timeout=10) as response:
                release = json.load(response)
        except HTTPError as exc:
            if exc.code != 404 or attempt == 11:
                raise
        else:
            require(release['info']['name'] == NAME and release['info']['version'] == VERSION,
                    'Index returned a different package or version')
            files = {row['filename']: row['digests']['sha256'] for row in release['urls']}
            if files == wanted and len(release['urls']) == len(wanted):
                return
            require(set(files.items()) < set(wanted.items()), 'Index artifacts differ from this run')
        time.sleep(5)
    raise SystemExit('Some release files are not visible on the index')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--index', choices=('test.pypi.org', 'pypi.org'))
    args = parser.parse_args()
    if args.index:
        verify_index(args.directory, args.index)
    else:
        inspect_distribution(args.directory)
    print(f'Verified {NAME} {VERSION} wheel and sdist')


if __name__ == '__main__':
    main()
