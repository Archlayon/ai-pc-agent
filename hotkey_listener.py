"""
Global hotkey listener for the AI PC Agent, using the xdg-desktop-portal
GlobalShortcuts interface (the proper Wayland-native way to get a global
hotkey, since pynput/X11-style listeners don't work under Wayland).

Bound to Control+L by default. Pressing it prompts for a request and sends
it to the running main agent (or falls back to direct LLM call).

Requires:
    sudo dnf install python3-dbus python3-gobject
    pip install google-genai --break-system-packages

Also requires the matching .desktop file to be installed first:
    cp com.layon.aiagent.desktop ~/.local/share/applications/
"""
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from settings import get_settings
try:
    from whisper_input import listen as voice_listen
except Exception:
    voice_listen = None

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_OBJ = "/org/freedesktop/portal/desktop"
GS_IFACE = "org.freedesktop.portal.GlobalShortcuts"
REG_IFACE = "org.freedesktop.host.portal.Registry"
APP_ID = "com.layon.aiagent"

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
portal = bus.get_object(PORTAL_BUS, PORTAL_OBJ)

_sender = bus.get_unique_name()[1:].replace(".", "_")

_main_agent = None
_widget = None


def request_path(token):
    return f"{PORTAL_OBJ}/request/{_sender}/{token}"


def set_main_agent(agent):
    global _main_agent
    _main_agent = agent


def set_widget(widget):
    global _widget
    _widget = widget


def on_activated(session_handle, shortcut_id, timestamp, options):
    import subprocess
    subprocess.Popen(["python3", "-m", "main_widget"], cwd="/home/layon/ai-pc-agent")


def bind_shortcuts(session_handle):
    request_token = "bind1"

    def on_response(response_code, results):
        if response_code != 0:
            print(f"[error] BindShortcuts failed: code {response_code}")
            return
        print("[ok] Shortcut registered. Press Control+L to activate.")
        for s in results.get("shortcuts", []):
            print(f"  -> {s}")

    bus.add_signal_receiver(
        on_response,
        signal_name="Response",
        dbus_interface="org.freedesktop.portal.Request",
        path=request_path(request_token),
    )

    shortcuts = dbus.Array(
        [
            dbus.Struct(
                (
                    "summon-widget",
                    dbus.Dictionary(
                        {"description": dbus.String("Summon AI PC Agent")},
                        signature="sv",
                    ),
                ),
                signature="sa{sv}",
            )
        ],
        signature="(sa{sv})",
    )

    gs = dbus.Interface(portal, GS_IFACE)
    gs.BindShortcuts(
        session_handle,
        shortcuts,
        "",
        {"handle_token": request_token},
    )


def create_session():
    request_token = "create1"

    def on_response(response_code, results):
        if response_code != 0:
            print(f"[error] CreateSession failed: code {response_code}")
            return
        session_handle = results["session_handle"]
        print(f"[ok] Session created: {session_handle}")
        bind_shortcuts(session_handle)

    bus.add_signal_receiver(
        on_response,
        signal_name="Response",
        dbus_interface="org.freedesktop.portal.Request",
        path=request_path(request_token),
    )

    gs = dbus.Interface(portal, GS_IFACE)
    gs.CreateSession(
        {
            "handle_token": request_token,
            "session_handle_token": "aiagent_session1",
        }
    )


def main():
    dbus.Interface(portal, REG_IFACE).Register(APP_ID, {})

    bus.add_signal_receiver(
        on_activated,
        signal_name="Activated",
        dbus_interface=GS_IFACE,
    )

    create_session()

    print("[hotkey] Listening for Control+L... (Ctrl+C to quit)")
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n[hotkey] Stopped.")


if __name__ == "__main__":
    main()
