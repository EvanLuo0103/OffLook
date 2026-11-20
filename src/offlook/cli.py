"""Command-line entry point; imports do not start Tk or register hotkeys."""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from contextlib import redirect_stdout
from dataclasses import replace
from importlib.metadata import version
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys

_SETTING_TYPES = {
    'max_file_size_bytes': int,
    'preview_timeout_seconds': float,
    'supported_extensions': tuple,
    'always_on_top': bool,
    'hotkey_enabled': bool,
    'hotkey': str,
    'search_hotkey': str,
    'diff_hotkey': str,
    'convert_hotkey': str,
    'filter_hotkey': str,
    'ai_hotkey': str,
    'convert_mode': str,
    'language': str,
}


def main(argv: Sequence[str] | None = None, *, windowed: bool = False) -> int:
    """Parse CLI options and return 0, 1, 2, or 130 without uploading files."""
    multiprocessing.freeze_support()
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
    filters.add_argument('--gui', action='store_true', help='Open the Search & filter window; --kind preselects categories')
    search = commands.add_parser('search', help='Search local files recursively by name and category')
    search.add_argument('folder', metavar='FOLDER', nargs='?', default='.',
                        help='Folder to search (default: current working directory)')
    search.add_argument('--name', metavar='TEXT', default='', help='Case-insensitive file name substring')
    search.add_argument('--kind', metavar='KIND', choices=kind_values, action='append', default=[],
                        help=f'Single category: {", ".join(kind_values)}')
    compare = commands.add_parser('compare', help='Compare two local text or DOCX files',
                                  description='Print a unified diff; exit 0 if identical, 1 if different, or 2 on error.')
    compare.add_argument('old', metavar='OLD')
    compare.add_argument('new', metavar='NEW')
    convert = commands.add_parser('convert', help='Convert local files or list shared output formats')
    convert.add_argument('files', metavar='FILE', nargs='+')
    target = convert.add_mutually_exclusive_group(required=True)
    target.add_argument('--to', metavar='FORMAT', help='Target format (e.g. txt, pdf, extract for ZIP)')
    target.add_argument('--list-targets', action='store_true', help='List shared formats without writing files')
    convert.add_argument('--mode', choices=('auto', 'text', 'office'), default='auto')
    convert.add_argument('--output-dir', metavar='DIR', help='Existing output directory (default: next to sources)')
    for operation in ('copy', 'move'):
        transfer = commands.add_parser(operation, help=f'{operation.title()} local files into a directory')
        transfer.add_argument('files', metavar='FILE', nargs='+')
        transfer.add_argument('--to', required=True, metavar='DIR', help='Existing destination directory')
        transfer.add_argument('--conflict', choices=('rename', 'skip', 'overwrite'), default='rename')
    organize = commands.add_parser('organize', help='Move files recursively into category directories')
    organize.add_argument('folder', metavar='FOLDER')
    organize.add_argument('--to', required=True, metavar='DIR', help='Existing directory outside the source tree')
    organize.add_argument('--kind', metavar='KIND', choices=kind_values, action='append', default=[],
                          help=f'Repeatable category: {", ".join(kind_values)}')
    settings = commands.add_parser('settings', help='Read or save preferences and shortcut bindings')
    setting_actions = settings.add_subparsers(dest='operation', required=True)
    setting_actions.add_parser('show', help='Print preferences and shortcut bindings as JSON (no AI connection settings)')
    setting = setting_actions.add_parser('set', help='Save one preference or shortcut binding')
    setting.add_argument('key', choices=tuple(_SETTING_TYPES))
    setting.add_argument('values', metavar='VALUE', nargs='*',
                         help='One value per key; booleans use true/false, suffixes allow zero or more')
    startup = commands.add_parser('startup', help='Manage current-user startup at Windows sign-in')
    startup.add_argument('operation', choices=('status', 'enable', 'disable'))
    path = commands.add_parser('path', help='Add this installation to the current user PATH')
    path.add_argument('operation', choices=('add',))
    args = parser.parse_args(argv)
    if windowed and not (args.command in (None, 'preview') or (args.command == 'filter' and args.gui)):
        parser.error('Use ol.exe for terminal commands')
    if args.background and args.command is not None:
        parser.error('--background cannot be combined with a subcommand')
    if sys.platform != 'win32':
        print('OffLook currently supports Windows only', file=sys.stderr)
        return 2
    if args.command == 'preview' and not args.filepath.strip():
        parser.error('File path cannot be empty')
    from offlook.core.context import create_context
    from offlook.core.errors import OffLookError

    if args.command in ('search', 'compare', 'convert', 'copy', 'move', 'organize', 'path') and args.config is not None:
        parser.error('--config is not used by this command')
    if args.command == 'startup' and args.config is not None and args.operation != 'enable':
        parser.error('--config is only supported with startup enable')
    if args.command == 'settings' and args.operation == 'set':
        try:
            setting_value = _parse_setting(args.key, args.values)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == 'search' and len(args.kind) > 1:
        parser.error('search accepts only one --kind; use filter for multiple kinds')
    if args.command in ('search', 'filter', 'organize') and not args.folder.strip():
        parser.error('Folder path cannot be empty')
    if args.command == 'compare' and (not args.old.strip() or not args.new.strip()):
        parser.error('File path cannot be empty')
    if args.command in ('convert', 'copy', 'move') and any(not name.strip() for name in args.files):
        parser.error('File path cannot be empty')
    if args.command in ('copy', 'move', 'organize') and not args.to.strip():
        parser.error('Destination path cannot be empty')
    if args.command == 'convert' and args.output_dir is not None:
        if args.list_targets:
            parser.error('--output-dir is only supported with --to')
        if not args.output_dir.strip():
            parser.error('Destination path cannot be empty')
    if args.command == 'filter':
        if args.gui and (args.name is not None or args.ext):
            parser.error('--gui cannot be combined with --name or --ext')
        if not args.gui and args.config is not None:
            parser.error('--config is only supported with filter --gui')
    try:
        if args.command == 'search':
            from offlook.core import find_files

            kind = FileKind(args.kind[0]) if args.kind else None
            _write_lines(str(row.path) for row in find_files(args.folder, filename=args.name, kind=kind))
            return 0
        if args.command == 'compare':
            from offlook.core.file_comparison import compare_files, iter_unified_diff

            comparison = compare_files(args.old, args.new)
            _write_lines(iter_unified_diff(comparison))
            return int(comparison.changed)
        if args.command == 'convert':
            return _convert(args)
        if args.command in ('copy', 'move', 'organize'):
            return _transfer(args)
        if args.command == 'settings':
            manager = create_context(args.config).config
            if args.operation == 'show':
                _write_lines((json.dumps({key: getattr(manager.current, key) for key in _SETTING_TYPES},
                                         ensure_ascii=False),))
            else:
                manager.update(replace(manager.current, **{args.key: setting_value}), persist=True)
                if manager.credential_warning:
                    print(f'OffLook: {manager.credential_warning}', file=sys.stderr)
            return 0
        if args.command == 'startup':
            from offlook.platforms.windows_startup import StartupManager

            if args.config is not None:
                args.config = create_context(args.config).config.path
            startup_manager = StartupManager(args.config)
            if args.operation == 'status':
                _write_lines(('enabled' if startup_manager.is_enabled() else 'disabled',))
            else:
                startup_manager.set_enabled(args.operation == 'enable')
            return 0
        if args.command == 'path':
            return _add_user_path()
        if args.command == 'filter':
            kinds = tuple(FileKind(value) for value in args.kind)
            if not args.gui:
                from offlook.core import filter_files

                rows = filter_files(args.folder, filename=args.name or '', kinds=kinds, extensions=args.ext)
                _write_lines(str(row.path) for row in rows)
                return 0
            from offlook.core.search import _validate_folder

            folder = _validate_folder(args.folder)
        context = create_context(args.config)
        if args.command == 'diagnose-search-shortcut':
            from offlook.diagnostics import run_search_shortcut_diagnostic

            return run_search_shortcut_diagnostic(context.config.current.search_hotkey)
    except (OffLookError, OSError, UnicodeError, ImportError, RuntimeError) as exc:
        print(f'OffLook: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    try:
        from tkinter import TclError
    except ImportError as exc:
        print(f'OffLook dependency / desktop initialization failed: {exc}', file=sys.stderr)
        return 2
    try:
        import os

        from offlook.platforms.windows_launch import frozen_gui_executable

        gui = frozen_gui_executable() if args.background else None
        executable = Path(sys.executable)
        if args.background and executable.name.lower() not in ('pythonw.exe', 'offlook.exe' if gui else ''):
            if gui is None:
                pythonw = executable.with_name('pythonw.exe')
                if not pythonw.is_file():
                    print('pythonw.exe not found; cannot start without a console', file=sys.stderr)
                    return 2
                command = [str(pythonw), '-m', 'offlook']
            else:
                command = [str(gui)]
            if args.config:
                command.extend(['--config', str(context.config.path)])
            command.append('--background')
            env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1') if gui else None
            subprocess.Popen(command, creationflags=subprocess.DETACHED_PROCESS, env=env)
            return 0
        from offlook.gui import PreviewApplication

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


def _convert(args: argparse.Namespace) -> int:
    from offlook.core import convert_files, reachable_targets
    from offlook.platforms.windows_files import validate_local_file, validate_local_folder

    sources = tuple(validate_local_file(path) for path in args.files)
    if args.list_targets:
        _write_lines(target.lstrip('.') for target in reachable_targets(sources, args.mode))
        return 0
    directory = validate_local_folder(args.output_dir) if args.output_dir is not None else None
    with redirect_stdout(sys.stderr):
        outcomes = convert_files(sources, args.to, directory=directory, mode=args.mode)
    _write_lines(str(path.absolute()) for outcome in outcomes for path in outcome.outputs)
    return 0


def _transfer(args: argparse.Namespace) -> int:
    from offlook.core import FileAccessError, FileKind, copy_files, move_files, organize_by_kind
    from offlook.platforms.windows_files import validate_local_folder

    destination = validate_local_folder(args.to)
    if args.command == 'organize':
        source = validate_local_folder(args.folder)
        if destination.is_relative_to(source):
            raise FileAccessError('Destination must be outside the source folder')
        results = organize_by_kind(source, destination, kinds=tuple(FileKind(value) for value in args.kind))
    else:
        transfer = copy_files if args.command == 'copy' else move_files
        results = transfer(args.files, destination, conflict=args.conflict)
    _write_lines(json.dumps({
        'source': str(item.source.absolute()), 'destination': str(item.destination.absolute()),
        'status': item.status, 'message': item.message,
    }, ensure_ascii=False) for item in results)
    failed = False
    for item in results:
        if item.status == 'failed':
            print(f'OffLook: {item.source}: {item.message}', file=sys.stderr)
            failed = True
    return 2 if failed else 0


def _parse_setting(key: str, values: Sequence[str]) -> object:
    kind = _SETTING_TYPES[key]
    if kind is tuple:
        return tuple(values)
    if len(values) != 1:
        raise ValueError(f'{key} requires exactly one value')
    value = values[0]
    if kind is bool:
        if value not in ('true', 'false'):
            raise ValueError(f'{key} must be true or false')
        return value == 'true'
    try:
        return kind(value)
    except ValueError:
        raise ValueError(f'{key} requires a {kind.__name__} value') from None


def _add_user_path() -> int:
    from offlook.platforms.windows_environment import add_offlook_to_user_path

    result = add_offlook_to_user_path()
    _write_lines((str(result.scripts_dir),))
    if not result.broadcast_ok:
        print('OffLook: user PATH saved; open a new terminal to pick it up', file=sys.stderr)
    if result.conflicting_executable is not None:
        print(f'OffLook: another installation takes precedence: {result.conflicting_executable}; '
              f'run the command from {result.scripts_dir}', file=sys.stderr)
    return 0


def _write_lines(lines: Iterable[str]) -> None:
    """Keep redirected records UTF-8 with LF, independent of console encoding."""
    stdout = sys.stdout
    binary = getattr(stdout, 'buffer', None)
    piped = binary is not None and not stdout.isatty()
    wrote = False
    for line in lines:
        if piped:
            binary.write(f'{line}\n'.encode('utf-8'))
        else:
            print(line, file=stdout)
        wrote = True
    if wrote:
        (binary if piped else stdout).flush()


if __name__ == '__main__':
    raise SystemExit(main())
