"""Manage this user's explicit Windows logon entry without import-time changes."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

from offlook.core.errors import OffLookError
from offlook.platforms.windows_launch import frozen_gui_executable


class StartupManager:
    """Read or change one HKCU Run value for the current Python installation.

    ``config_path`` is made absolute for logon, whose working directory may
    differ. ``registry_path`` and ``value_name`` allow isolated registry tests;
    production callers should retain their defaults. Construction never reads
    or writes the registry. Enabling requires an importable OffLook entry point
    and a real sibling pythonw.exe; it does not install or launch anything.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        registry_path: str = r"Software\Microsoft\Windows\CurrentVersion\Run",
        value_name: str = "OffLook",
    ) -> None:
        """Store the entry location and absolute config path, or raise OffLookError."""
        try:
            self._config_path = Path(os.path.abspath(config_path)) if config_path is not None else None
        except OSError as exc:
            raise OffLookError("Cannot obtain the absolute path of the startup configuration file") from exc
        self._registry_path = registry_path
        self._value_name = value_name

    @staticmethod
    def _registry() -> ModuleType:
        """Return Windows' registry module, or raise OffLookError off Windows."""
        if sys.platform != "win32":
            raise OffLookError("OffLook startup-at-login settings are supported only on Windows")
        import winreg

        return winreg

    def is_enabled(self) -> bool:
        """Check this installation's login entry (any OffLook entry for pip installs)."""
        registry = self._registry()
        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER, self._registry_path, 0, registry.KEY_QUERY_VALUE
            ) as key:
                command, _ = registry.QueryValueEx(key, self._value_name)
            executable = frozen_gui_executable()
            return executable is None or self._owns_command(command, executable)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise OffLookError("Cannot read Windows startup-at-login settings") from exc

    @staticmethod
    def _owns_command(command: object, executable: Path) -> bool:
        if not isinstance(command, str) or not command.strip() or '\x00' in command:
            return False
        from win32api import CommandLineToArgv

        first = Path(CommandLineToArgv(command.lstrip())[0])
        return first.is_absolute() and os.path.normcase(os.path.normpath(first)) == os.path.normcase(
            os.path.normpath(executable))

    def remove_if_executable(self, executable: Path) -> None:
        """Remove the Run entry only when its executable is from this install."""
        registry = self._registry()
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, self._registry_path, 0,
                                  registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE) as key:
                command, _ = registry.QueryValueEx(key, self._value_name)
                if self._owns_command(command, executable):
                    registry.DeleteValue(key, self._value_name)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise OffLookError('Cannot remove Windows startup-at-login settings') from exc

    def _startup_command(self) -> str:
        """Build a quoted command that works at sign-in without a console."""
        gui = frozen_gui_executable()
        if gui is not None:
            arguments = [str(gui)]
        else:
            try:
                if not sys.executable:
                    raise OffLookError('Cannot locate the current Python executable')
                executable = Path(sys.executable).absolute()
                pythonw = executable.with_name('pythonw.exe')
                if not executable.is_file() or not pythonw.is_file():
                    raise OffLookError('The current Python environment is missing pythonw.exe; startup at login cannot be configured')
                if importlib.util.find_spec('offlook.__main__') is None:
                    raise OffLookError('OffLook was not found in the current Python environment; install the package first')
            except (OSError, ImportError, ValueError) as exc:
                raise OffLookError('Cannot check the Python environment required for startup at login') from exc
            arguments = [str(pythonw), '-m', 'offlook']
        if self._config_path is not None:
            arguments.extend(("--config", str(self._config_path)))
        arguments.append("--background")
        command = subprocess.list2cmdline(arguments)
        if len(command.encode('utf-16-le')) // 2 > 260:
            raise OffLookError('The startup command exceeds the Windows 260-character limit')
        return command

    def set_enabled(self, enabled: bool) -> None:
        """Set or remove only this value; preserve other values and the Run key.

        ``enabled`` must be a bool. Missing entries are already disabled.
        Environment or registry failures raise OffLookError with their cause;
        validation occurs before any enable write, with no shell or batch file.
        """
        if not isinstance(enabled, bool):
            raise OffLookError("The startup-at-login setting must be a boolean")
        registry = self._registry()
        executable = frozen_gui_executable()
        if executable is not None and not enabled:
            self.remove_if_executable(executable)
            return
        command = self._startup_command() if enabled else None
        try:
            if enabled:
                with registry.CreateKeyEx(
                    registry.HKEY_CURRENT_USER, self._registry_path, 0,
                    registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE,
                ) as key:
                    if executable is not None:
                        try:
                            previous, _ = registry.QueryValueEx(key, self._value_name)
                        except FileNotFoundError:
                            pass
                        else:
                            if not self._owns_command(previous, executable):
                                raise OffLookError('Another OffLook installation starts at sign-in; disable it there first')
                    registry.SetValueEx(key, self._value_name, 0, registry.REG_SZ, command)
            else:
                try:
                    with registry.OpenKey(
                        registry.HKEY_CURRENT_USER, self._registry_path, 0, registry.KEY_SET_VALUE
                    ) as key:
                        registry.DeleteValue(key, self._value_name)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise OffLookError("Cannot change Windows startup-at-login settings") from exc
