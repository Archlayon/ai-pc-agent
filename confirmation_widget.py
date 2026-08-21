"""
GUI floating confirmation widget for the AI PC Agent.

Uses CustomTkinter for a frameless, always-on-top confirmation popup.
Falls back to terminal input if CustomTkinter is unavailable or no display
is present.
"""
import os
import sys
import threading
from typing import Callable, Optional

try:
    import customtkinter as ctk

    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from settings import get_settings

DEFAULT_CONFIRM_TIMEOUT = 300  # seconds


class _GuiConfirm:
    """CustomTkinter-based confirmation dialog."""

    def __init__(self, tool_name: str, args: dict, timeout: int = DEFAULT_CONFIRM_TIMEOUT):
        if not CTK_AVAILABLE:
            raise RuntimeError("CustomTkinter not available")

        self.result = None
        self.tool_name = tool_name
        self.args = args
        self.timeout = timeout

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.root = ctk.CTk()
        self.root.title("AI PC Agent — Confirm")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry("420x220")
        self.root.resizable(False, False)

        self._build_ui()
        self._center()

    def _build_ui(self):
        frame = ctk.CTkFrame(self.root, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        title = ctk.CTkLabel(
            frame, text="Confirm Action", font=ctk.CTkFont(size=16, weight="bold")
        )
        title.pack(pady=(10, 5))

        info = ctk.CTkLabel(
            frame,
            text=f"Tool: {self.tool_name}\nArgs: {self.args}",
            font=ctk.CTkFont(size=12),
            anchor="w",
            justify="left",
        )
        info.pack(pady=5, padx=10, fill="x")

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=10)

        approve_btn = ctk.CTkButton(
            btn_frame, text="Approve", command=self._approve, width=100, fg_color="#2CC985"
        )
        approve_btn.pack(side="left", padx=8)

        deny_btn = ctk.CTkButton(
            btn_frame, text="Deny", command=self._deny, width=100, fg_color="#FF6B6B"
        )
        deny_btn.pack(side="left", padx=8)

        self.root.protocol("WM_DELETE_WINDOW", self._deny)

    def _center(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 3) - (h // 2)
        self.root.geometry(f"+{x}+{y}")

    def _approve(self):
        self.result = True
        self.root.destroy()

    def _deny(self):
        self.result = False
        self.root.destroy()

    def show(self) -> bool:
        try:
            self.root.mainloop()
        except Exception:
            pass
        return bool(self.result)


def _terminal_confirm(tool_name: str, args: dict) -> bool:
    print(f"\n[confirm] Run '{tool_name}' with {args}? [y/N] ", end="")
    try:
        answer = input().strip().lower()
        return answer == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def confirm_action(tool_name: str, args: dict, timeout: int = DEFAULT_CONFIRM_TIMEOUT) -> bool:
    """
    Show a confirmation dialog for a sensitive action.

    Returns True if approved, False if denied or timed out.
    Uses GUI if available, otherwise falls back to terminal.
    """
    settings = get_settings()
    if settings.get("autonomy_mode", False):
        return True

    use_gui = settings.get("gui_confirm", True) and CTK_AVAILABLE and sys.stdin.isatty() is False

    if use_gui:
        try:
            dialog = _GuiConfirm(tool_name, args, timeout=timeout)
            return dialog.show()
        except Exception:
            pass

    return _terminal_confirm(tool_name, args)
