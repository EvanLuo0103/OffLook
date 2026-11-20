"""Entry point shared by the two frozen Windows launchers."""
import multiprocessing
import sys
from pathlib import Path


if __name__ == '__main__':
    multiprocessing.freeze_support()
    windowed = Path(sys.executable).name.casefold() == 'offlook.exe'
    if not windowed and sys.argv[1:] == ['--installer-remove-integration']:
        from offlook.core.errors import OffLookError
        from offlook.platforms.windows_environment import remove_frozen_install_integration

        try:
            remove_frozen_install_integration()
        except OffLookError as exc:
            print(f'OffLook: {exc}', file=sys.stderr)
            raise SystemExit(2) from None
        raise SystemExit(0)

    from offlook.cli import main

    if not windowed:
        raise SystemExit(main())

    import ctypes
    from contextlib import redirect_stderr
    from io import StringIO

    errors = StringIO()
    with redirect_stderr(errors):
        try:
            code = main(windowed=True)
        except SystemExit as exc:
            code = exc.code
    if code == 2:
        ctypes.windll.user32.MessageBoxW(None, errors.getvalue().strip() or 'OffLook could not start.',
                                       'OffLook', 0x10)
    raise SystemExit(code)
