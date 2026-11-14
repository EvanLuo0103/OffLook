"""Manage this user's explicit Windows logon entry without import-time changes."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

from offlook.core.errors import OffLookError


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
        """Return whether this HKCU value actually exists; wrap registry OSError.

        The result is read afresh, not cached or inferred from application
        configuration. A missing key or value means disabled.
        """
        registry = self._registry()
        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER, self._registry_path, 0, registry.KEY_QUERY_VALUE
            ) as key:
                registry.QueryValueEx(key, self._value_name)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise OffLookError("Cannot read Windows startup-at-login settings") from exc

    def _startup_command(self) -> str:
        """Build a quoted pythonw command, or raise OffLookError if unavailable.

        The sibling executable uses the current interpreter's environment.
        OffLook must remain installed/importable there after logon; this check
        verifies the current process can locate its module entry point, not a
        promise about later changes to that environment.
        """
        try:
            if not sys.executable:
                raise OffLookError("Cannot locate the current Python executable")
            executable = Path(sys.executable).absolute()
            pythonw = executable.with_name("pythonw.exe")
            if not executable.is_file() or not pythonw.is_file():
                raise OffLookError("The current Python environment is missing pythonw.exe; startup at login cannot be configured")
            if importlib.util.find_spec("offlook.__main__") is None:
                raise OffLookError("OffLook was not found in the current Python environment; install the package first")
        except OSError as exc:
            raise OffLookError("Cannot check the Python environment required for startup at login") from exc
        except (ImportError, ValueError) as exc:
            raise OffLookError("The current Python environment cannot load OffLook; install the package first") from exc
        arguments = [str(pythonw), "-m", "offlook"]
        if self._config_path is not None:
            arguments.extend(("--config", str(self._config_path)))
        arguments.append("--background")
        return subprocess.list2cmdline(arguments)

    def set_enabled(self, enabled: bool) -> None:
        """Set or remove only this value; preserve other values and the Run key.

        ``enabled`` must be a bool. Missing entries are already disabled.
        Environment or registry failures raise OffLookError with their cause;
        validation occurs before any enable write, with no shell or batch file.
        """
        if not isinstance(enabled, bool):
            raise OffLookError("The startup-at-login setting must be a boolean")
        registry = self._registry()
        command = self._startup_command() if enabled else None
        try:
            if enabled:
                with registry.CreateKeyEx(
                    registry.HKEY_CURRENT_USER, self._registry_path, 0, registry.KEY_SET_VALUE
                ) as key:
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
