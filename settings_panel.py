"""
GUI settings panel for the AI PC Agent.

Frameless, always-on-top window for editing agent settings.
"""
import customtkinter as ctk

from settings import get_settings, update_settings

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class SettingsPanel:
    def __init__(self, on_close=None):
        self.on_close = on_close
        self.root = ctk.CTk()
        self.root.title("AI PC Agent Settings")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry("420x520")
        self.root.resizable(False, False)

        self._build_ui()
        self._center()
        self._make_draggable()

    def _build_ui(self):
        header = ctk.CTkFrame(self.root, height=30, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title = ctk.CTkLabel(header, text="Settings", font=ctk.CTkFont(size=12, weight="bold"))
        title.pack(side="left", padx=10, pady=5)

        close_btn = ctk.CTkButton(header, text="✕", width=30, height=24,
                                   command=self._close, fg_color="transparent",
                                   text_color=("gray", "white"), hover_color=("gray70", "gray30"))
        close_btn.pack(side="right", padx=5, pady=3)

        scroll = ctk.CTkScrollableFrame(self.root)
        scroll.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        settings = get_settings()

        self.vars = {}

        toggles = [
            ("autonomy_mode", "Full Autonomy Mode (disables confirmations)"),
            ("voice_mode", "Voice Input Mode"),
            ("gui_confirm", "GUI Confirmation Dialogs"),
            ("confirm_gate", "Confirmation Gate (sensitive actions)"),
        ]

        for key, label in toggles:
            var = ctk.BooleanVar(value=settings.get(key, False))
            self.vars[key] = var
            cb = ctk.CTkSwitch(scroll, text=label, variable=var, command=lambda k=key, v=var: self._update(k, v.get()))
            cb.pack(anchor="w", pady=5)

        ctk.CTkLabel(scroll, text="LLM Model", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(15, 5))
        self.model_var = ctk.StringVar(value=settings.get("llm_model", "gemini-flash-latest"))
        model_menu = ctk.CTkOptionMenu(scroll, variable=self.model_var, values=["gemini-flash-latest", "gemini-pro-latest"],
                                        command=lambda v: self._update("llm_model", v))
        model_menu.pack(fill="x", pady=5)

        ctk.CTkLabel(scroll, text="Whisper Model", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(15, 5))
        self.whisper_var = ctk.StringVar(value=settings.get("whisper_model", "small"))
        whisper_menu = ctk.CTkOptionMenu(scroll, variable=self.whisper_var, values=["tiny", "base", "small", "medium"],
                                         command=lambda v: self._update("whisper_model", v))
        whisper_menu.pack(fill="x", pady=5)

        ctk.CTkLabel(scroll, text=f"Max Workers: {settings.get('max_workers', 3)}", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(15, 5))
        self.workers_var = ctk.IntVar(value=settings.get("max_workers", 3))
        workers_slider = ctk.CTkSlider(scroll, from_=1, to=10, number_of_steps=9, variable=self.workers_var,
                                       command=lambda v: self._update("max_workers", int(v)))
        workers_slider.pack(fill="x", pady=5)

        ctk.CTkLabel(scroll, text=f"Max Fixers: {settings.get('max_fixers', 2)}", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(15, 5))
        self.fixers_var = ctk.IntVar(value=settings.get("max_fixers", 2))
        fixers_slider = ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4, variable=self.fixers_var,
                                      command=lambda v: self._update("max_fixers", int(v)))
        fixers_slider.pack(fill="x", pady=5)

        ctk.CTkLabel(scroll, text=f"Idle Grace (seconds): {settings.get('idle_grace_seconds', 3600)}", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(15, 5))
        self.grace_var = ctk.IntVar(value=settings.get("idle_grace_seconds", 3600))
        grace_slider = ctk.CTkSlider(scroll, from_=300, to=7200, number_of_steps=22, variable=self.grace_var,
                                     command=lambda v: self._update("idle_grace_seconds", int(v)))
        grace_slider.pack(fill="x", pady=5)

    def _center(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 3) - (h // 2)
        self.root.geometry(f"+{x}+{y}")

    def _make_draggable(self):
        header = self.root.winfo_children()[0]
        header.bind("<ButtonPress-1>", self._start_move)
        header.bind("<ButtonRelease-1>", self._stop_move)
        header.bind("<B1-Motion>", self._on_move)

    def _start_move(self, event):
        self._x = event.x
        self._y = event.y

    def _stop_move(self, event):
        self._x = None
        self._y = None

    def _on_move(self, event):
        deltax = event.x - self._x
        deltay = event.y - self._y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def _update(self, key, value):
        update_settings({key: value})

    def _close(self):
        self.root.destroy()
        if self.on_close:
            self.on_close()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def run(self):
        self.root.mainloop()
