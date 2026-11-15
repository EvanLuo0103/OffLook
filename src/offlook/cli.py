"""Command-line entry point; imports do not start Tk or register hotkeys."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from importlib.metadata import version
import multiprocessing
from pathlib import Path
import subprocess
import sys


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI options and return 0, 1, 2, or 130 without uploading files."""
    parser = argparse.ArgumentParser(prog='offlook', description='Offline file previews for Windows')
    parser.add_argument('--version', action='version', version=version('offlook'))
    parser.add_argument('--config', metavar='PATH', help='Path to the local JSON configuration')
    parser.add_argument('--background', action='store_true', help='Hide to the system tray and listen in the background')
    commands = parser.add_subparsers(dest='command')
    preview = commands.add_parser('preview', help='Preview a local file')
    preview.add_argument('filepath')
    preview.add_argument('--topmost', action='store_const', const=True, default=None)
    commands.add_parser(
        'diagnose-search-shortcut',
        help='Test the configured search shortcut and Explorer folder selection',
    )
    args = parser.parse_args(argv)
    if args.background and args.command is not None:
        parser.error('--background cannot be combined with a subcommand')
    if sys.platform != 'win32':
        print('OffLook currently supports Windows only', file=sys.stderr)
        return 2
    if args.command == 'preview' and not args.filepath.strip():
        parser.error('File path cannot be empty')
    multiprocessing.freeze_support()
    from offlook.core.context import create_context
    from offlook.core.errors import OffLookError
    try:
        context = create_context(args.config)
        if args.command == 'diagnose-search-shortcut':
            from offlook.diagnostics import run_search_shortcut_diagnostic
            return run_search_shortcut_diagnostic(context.config.current.search_hotkey)
        from tkinter import TclError
        from offlook.gui import PreviewApplication
        if args.background and Path(sys.executable).name.lower() != 'pythonw.exe':
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            if not pythonw.is_file():
                print('pythonw.exe not found; cannot start without a console', file=sys.stderr)
                return 2
            command = [str(pythonw), '-m', 'offlook']
            if args.config:
                command.extend(['--config', str(Path(args.config).absolute())])
            command.append('--background')
            subprocess.Popen(command, creationflags=subprocess.DETACHED_PROCESS)
            return 0
        app = PreviewApplication(context, resident=args.command is None,
                                 always_on_top=getattr(args, 'topmost', None),
                                 background=args.background, config_path=args.config)
        if args.command == 'preview':
            app.open(args.filepath)
        return app.run()
    except OffLookError as exc:
        print(f'OffLook: {exc}', file=sys.stderr)
        return 2
    except (ImportError, RuntimeError, OSError) as exc:
        print(f'OffLook dependency / desktop initialization failed: {exc}', file=sys.stderr)
        return 2
    except TclError as exc:
        print(f'OffLook could not create the preview window: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
