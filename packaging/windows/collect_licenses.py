"""Copy third-party and project notices into the frozen installation."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def collect(bundle: Path) -> None:
    pending = [('offlook', 'office'), ('PyInstaller', '')]
    seen = set()
    while pending:
        name, extra = pending.pop()
        identity = canonicalize_name(name)
        if identity in seen:
            continue
        seen.add(identity)
        dist = metadata.distribution(name)
        for line in dist.requires or ():
            req = Requirement(line)
            if req.marker is None or req.marker.evaluate({'extra': extra}):
                pending.append((req.name, ''))
        for entry in dist.files or ():
            parts = entry.parts
            for index, part in enumerate(parts[:-1]):
                if part.endswith('.dist-info'):
                    relative = parts[index + 1:]
                    if relative[0] == 'licenses' or entry.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                        target = bundle.joinpath('licenses', identity, *relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(dist.locate_file(entry), target)
                    break
            else:
                if entry.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')) and '..' not in parts:
                    target = bundle.joinpath('licenses', identity, *parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(dist.locate_file(entry), target)
    shutil.copyfile(Path(__file__).resolve().parents[2] / 'LICENSE', bundle / 'LICENSE')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        target = bundle / 'licenses' / 'python' / 'LICENSE.txt'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(python_license, target)


if __name__ == '__main__':
    collect(Path(sys.argv[1]))
