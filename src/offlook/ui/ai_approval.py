"""A single run's one-shot approvals; no Tk calls on the worker thread."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING
import unicodedata

from offlook.ui.i18n import tr
from offlook.platforms.windows_dpi import window_dpi
from offlook.ui.theme import size_window

if TYPE_CHECKING:
    from offlook.core.file_ops import AiWritePlan


@dataclass(eq=False)
class _AiApprovalRequest:
    plan: AiWritePlan
    deadline: float
    reply: queue.Queue[bool] = field(default_factory=lambda: queue.Queue(1))


class RunApprovals:
    def __init__(self, origin: str, *, timeout: float = 120.0):
        self.origin = origin
        self.timeout = timeout
        self.requests: queue.SimpleQueue[_AiApprovalRequest] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._pending: _AiApprovalRequest | None = None
        self._denied = False

    def request(self, plan: AiWritePlan) -> bool:
        with self._lock:
            if self._denied or self._pending is not None:
                return False
            request = self._pending = _AiApprovalRequest(plan, time.monotonic() + self.timeout)
            self.requests.put(request)
        try:
            return request.reply.get(timeout=max(0, request.deadline - time.monotonic()))
        except queue.Empty:
            self.decide(request, False)
            return request.reply.get_nowait()

    def is_pending(self, request: _AiApprovalRequest) -> bool:
        with self._lock:
            return request is self._pending

    def decide(self, request: _AiApprovalRequest, allow: bool) -> None:
        with self._lock:
            if request is not self._pending:
                return
            approved = allow and time.monotonic() < request.deadline
            if not approved:
                self._denied = True
            self._pending = None
            request.reply.put_nowait(approved)

    def cancel(self) -> None:
        with self._lock:
            self._denied = True
            if self._pending is not None:
                self._pending.reply.put_nowait(False)
                self._pending = None


def display_path(path: Path) -> str:
    return ''.join(f'\\u{ord(c):04X}' if unicodedata.category(c) in ('Cc', 'Cf', 'Zl', 'Zp') else c
                   for c in str(path))


class AiApprovalDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, plan: AiWritePlan, decide: Callable[[bool], None]):
        super().__init__(parent)
        self.withdraw()
        self.title(tr('ai.approval'))
        size_window(self, window_dpi(self.winfo_id()), 680, 460, 420, 300)
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=tr('ai.op.' + plan.tool)).pack(anchor='w')
        controls = ttk.Frame(frame)
        controls.pack(side='bottom', fill='x', pady=(8, 0))
        deny = ttk.Button(controls, text=tr('ai.deny'), command=lambda: decide(False))
        deny.pack(side='right')
        ttk.Button(controls, text=tr('ai.approve'), command=lambda: decide(True)).pack(side='right', padx=8)
        text = tk.Text(frame, wrap='char', height=8, width=30)
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        lines = [f'{tr("ai.directory")}: {display_path(path)}' for path in plan.directories]
        for item in plan.items:
            lines.extend(('', f'{tr("ai.source")}: {display_path(item.source)}',
                          f'{tr("ai.destination")}: {display_path(item.destination)}'))
            if item.skip:
                lines.append(tr('ai.skip'))
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')
        self.protocol('WM_DELETE_WINDOW', lambda: decide(False))
        self.bind('<Escape>', lambda _: decide(False))
        self.bind('<Map>', lambda e: deny.focus_force() if e.widget is self else None)
        self.deiconify()
        self.lift()
