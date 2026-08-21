"""
Main floating agent widget for the AI PC Agent.

Frameless, always-on-top window for interaction with the agent.
Borrowed TTS/wake-word patterns from Ai-trading-agent.
"""
import os
import subprocess
import sys
import threading
import time

import customtkinter as ctk

from settings import get_settings

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except ImportError:
    _PYTTSX3_AVAILABLE = False


class AgentWidget:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("AI PC Agent")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry("500x600")
        self.root.resizable(False, False)

        self._listening = False
        self._listen_thread = None
        self._wake_listening = False
        self._wake_thread = None
        self._last_response = ""
        self._tts_engine = None

        if _PYTTSX3_AVAILABLE:
            try:
                self._tts_engine = pyttsx3.init()
                self._tts_engine.setProperty("rate", 175)
                self._tts_engine.setProperty("volume", 1.0)
            except Exception:
                self._tts_engine = None

        self._build_ui()
        self._center()
        self._make_draggable_and_resizable()
        self._focus_entry()

    def _focus_entry(self):
        self.root.after(200, self._do_focus)

    def _do_focus(self):
        try:
            self.entry.focus_set()
        except Exception:
            pass

    def _build_ui(self):
        header = ctk.CTkFrame(self.root, height=35, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title = ctk.CTkLabel(header, text="AI PC Agent", font=ctk.CTkFont(size=13, weight="bold"))
        title.pack(side="left", padx=12, pady=6)

        size_btn = ctk.CTkButton(header, text="⤢", width=28, height=24,
                                 command=self._toggle_size, fg_color="transparent",
                                 text_color=("gray", "white"), hover_color=("gray70", "gray30"))
        size_btn.pack(side="right", padx=2)

        listen_btn = ctk.CTkButton(header, text="🎤", width=28, height=24,
                                   command=self._toggle_listen, fg_color="transparent",
                                   text_color=("gray", "white"), hover_color=("gray70", "gray30"))
        listen_btn.pack(side="right", padx=2)

        wake_btn = ctk.CTkButton(header, text="🦾", width=28, height=24,
                                   command=self._toggle_wake, fg_color="transparent",
                                   text_color=("gray", "white"), hover_color=("gray70", "gray30"))
        wake_btn.pack(side="right", padx=2)

        speak_btn = ctk.CTkButton(header, text="🔊", width=28, height=24,
                                   command=self._speak_last, fg_color="transparent",
                                   text_color=("gray", "white"), hover_color=("gray70", "gray30"))
        speak_btn.pack(side="right", padx=2)

        close_btn = ctk.CTkButton(header, text="✕", width=28, height=24,
                                   command=self._hide, fg_color="transparent",
                                   text_color=("gray", "white"), hover_color=("gray70", "gray30"))
        close_btn.pack(side="right", padx=5, pady=3)

        self.chat_display = ctk.CTkTextbox(self.root, wrap="word", font=ctk.CTkFont(size=12))
        self.chat_display.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        self.chat_display.insert("end", "Agent ready. Type, use voice, or press Control+L.\n")
        self.chat_display.configure(state="disabled")

        input_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        input_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.entry = ctk.CTkEntry(input_frame, placeholder_text="Ask me anything...")
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.entry.bind("<Return>", lambda e: self._send())

        send_btn = ctk.CTkButton(input_frame, text="Send", command=self._send, width=60)
        send_btn.pack(side="right")

        self.status_label = ctk.CTkLabel(self.root, text="Ready", font=ctk.CTkFont(size=10), text_color="gray")
        self.status_label.pack(side="bottom", pady=(0, 5))

        self._last_response = ""

        self.root.bind("<Button-1>", lambda e: self._focus_entry())

    def _center(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 4) - (h // 2)
        self.root.geometry(f"+{x}+{y}")

    def _toggle_size(self):
        current = self.root.geometry().split("+")[0]
        w, h = map(int, current.split("x"))
        if w == 500 and h == 600:
            self.root.geometry("700x800")
        elif w == 700 and h == 800:
            self.root.geometry("900x1000")
        else:
            self.root.geometry("500x600")

    def _make_draggable_and_resizable(self):
        header = self.root.winfo_children()[0]
        header.bind("<ButtonPress-1>", self._start_move)
        header.bind("<ButtonRelease-1>", self._stop_move)
        header.bind("<B1-Motion>", self._on_move)

        grip = ctk.CTkFrame(self.root, width=16, height=16, corner_radius=8, fg_color="gray")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        grip.bind("<ButtonPress-1>", self._start_resize)
        grip.bind("<ButtonRelease-1>", self._stop_resize)
        grip.bind("<B1-Motion>", self._on_resize)

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

    def _start_resize(self, event):
        self._resize_x = event.x_root
        self._resize_y = event.y_root
        self._resize_w = self.root.winfo_width()
        self._resize_h = self.root.winfo_height()

    def _stop_resize(self, event):
        self._resize_x = None
        self._resize_y = None

    def _on_resize(self, event):
        if hasattr(self, '_resize_x') and self._resize_x is not None:
            new_w = max(300, self._resize_w + (event.x_root - self._resize_x))
            new_h = max(200, self._resize_h + (event.y_root - self._resize_y))
            self.root.geometry(f"{new_w}x{new_h}")

    def _append(self, text: str, tag: str = "user"):
        def _do():
            self.chat_display.configure(state="normal")
            self.chat_display.insert("end", f"\n[{tag}] {text}\n")
            self.chat_display.see("end")
            self.chat_display.configure(state="disabled")

        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def _send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append(text, "you")
        self._process_text(text)

    def _process_text(self, text: str):
        self.status_label.configure(text="Thinking...")

        def _run():
            try:
                from llm_client import ask_agent
                import io
                import sys

                old_stdout = sys.stdout
                sys.stdout = mystdout = io.StringIO()

                ask_agent(text)

                sys.stdout = old_stdout
                output = mystdout.getvalue()
                if output:
                    for line in output.strip().split("\n"):
                        if line:
                            self._append(line, "agent")
                            self._last_response = line
                self.root.after(0, lambda: self.status_label.configure(text="Ready"))
            except Exception as e:
                self.root.after(0, lambda: self._append(f"[error] {e}", "system"))
                self.root.after(0, lambda: self.status_label.configure(text="Error"))

        threading.Thread(target=_run, daemon=True).start()

    def _speak(self, text: str):
        if not text:
            return
        try:
            if _EDGE_TTS_AVAILABLE:
                import asyncio
                import tempfile

                async def _render():
                    communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    mp3_path = tmp.name
                    tmp.close()
                    await communicate.save(mp3_path)
                    self._play_audio(mp3_path)

                asyncio.run(_render())
                return
            if self._tts_engine is not None:
                self._tts_engine.say(text)
                self._tts_engine.runAndWait()
                return
            self._append("[error] No TTS engine available", "system")
        except Exception as e:
            self._append(f"[error] TTS failed: {e}", "system")

    def _play_audio(self, path: str):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["mpv", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            except Exception:
                pass

    def _speak_last(self):
        if self._last_response:
            self._speak(self._last_response)
        else:
            self._append("Nothing to speak yet.", "system")

    def _toggle_listen(self):
        if self._listening:
            self._listening = False
            self.status_label.configure(text="Ready")
        else:
            self._listening = True
            self.status_label.configure(text="Listening...")
            self._listen_thread = threading.Thread(target=self._continuous_listen, daemon=True)
            self._listen_thread.start()

    def _toggle_wake(self):
        if self._wake_listening:
            self._wake_listening = False
            self.status_label.configure(text="Ready")
        else:
            self._wake_listening = True
            self.status_label.configure(text="Wake word active...")
            self._wake_thread = threading.Thread(target=self._wake_listen_loop, daemon=True)
            self._wake_thread.start()

    def _wake_listen_loop(self):
        WAKE_WORDS = ["agent", "hey agent", "hello agent"]
        while self._wake_listening:
            try:
                import speech_recognition as sr
                recognizer = sr.Recognizer()
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = recognizer.listen(source, timeout=8, phrase_time_limit=4)
                text = recognizer.recognize_google(audio).lower().strip()
                if any(word in text for word in WAKE_WORDS):
                    self._append(f"[wake] detected: {text}", "system")
                    self.root.after(0, self.show)
                    self.root.after(100, self._focus_entry)
            except Exception:
                time.sleep(0.5)

    def _continuous_listen(self):
        while self._listening:
            try:
                import speech_recognition as sr
                recognizer = sr.Recognizer()
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = recognizer.listen(source, timeout=8, phrase_time_limit=5)
                text = recognizer.recognize_google(audio).lower().strip()
                if text and self._listening:
                    self._append(text, "you")
                    self._process_text(text)
            except Exception as e:
                self._append(f"[error] Voice: {e}", "system")
                time.sleep(1)

    def _hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    widget = AgentWidget()
    widget.run()
