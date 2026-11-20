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
    from offlook.core.files import FileKind

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
    filters = commands.add_parser(
        'filter', help='Filter local files recursively',
        description='Filter local files recursively; print one absolute path per line by default. '
                    'Repeated kinds or extensions match any value in their group; all groups must match.',
    )
    filters.add_argument('folder', metavar='FOLDER', nargs='?', default='.',
                         help='Folder to filter (default: current working directory)')
    kind_values = tuple(kind.value for kind in FileKind)
    filters.add_argument('--kind', metavar='KIND', choices=kind_values, action='append', default=[],
                         help=f'Repeatable category: {", ".join(kind_values)}')
    filters.add_argument('--ext', metavar='EXT', action='append', default=[],
                         help='Repeatable suffix with or without a dot; --ext= matches no suffix')
    filters.add_argument('--name', metavar='TEXT', default=None, help='Case-insensitive file name substring')
    filters.add_argument('--gui', action='store_true', help='Open the interactive filter window; --kind preselects categories')
    args = parser.parse_args(argv)
    if args.background and args.command is not None:
        parser.error('--background cannot be combined with a subcommand')
    if sys.platform != 'win32':
        print('OffLook currently supports Windows only', file=sys.stderr)
        return 2
    if args.command == 'preview' and not args.filepath.strip():
        parser.error('File path cannot be empty')
    if args.command == 'filter':
        if not args.folder.strip():
            parser.error('Folder path cannot be empty')
        if args.gui and (args.name is not None or args.ext):
            parser.error('--gui cannot be combined with --name or --ext')
        if not args.gui and args.config is not None:
            parser.error('--config is only supported with filter --gui')
        kinds = tuple(FileKind(value) for value in args.kind)
        if not args.gui:
            return _print_filter_results(args.folder, args.name or '', kinds, args.ext)
    multiprocessing.freeze_support()
    from offlook.core.context import create_context
    from offlook.core.errors import OffLookError
    try:
        context = create_context(args.config)
        if args.command == 'diagnose-search-shortcut':
            from offlook.diagnostics import run_search_shortcut_diagnostic
            return run_search_shortcut_diagnostic(context.config.current.search_hotkey)
        if args.command == 'filter':
            from offlook.core.search import _validate_folder
            folder = _validate_folder(args.folder)
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
        elif args.command == 'filter':
            app.open_filter(folder, kinds=kinds)
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


def _print_filter_results(folder, filename, kinds, extensions) -> int:
    from offlook.core import filter_files
    from offlook.core.errors import OffLookError

    try:
        rows = filter_files(folder, filename=filename, kinds=kinds, extensions=extensions)
        stdout = sys.stdout
        binary = getattr(stdout, 'buffer', None)
        if binary is not None and not stdout.isatty():
            for row in rows:
                binary.write(f'{row.path}\n'.encode('utf-8'))
            if rows:
                binary.flush()
        else:
            for row in rows:
                print(row.path, file=stdout)
            if rows:
                stdout.flush()
    except (OffLookError, OSError, UnicodeError) as exc:
        print(f'OffLook: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
