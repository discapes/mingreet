#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.13"
# dependencies = ["pygobject>=3.54.5"]
# ///
"""Minimal greetd greeter using GTK4."""

import json, os, socket, struct, sys, threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GUdev", "1.0")
from gi.repository import Gdk, GLib, GUdev, Gtk

CSS = """
entry { background: alpha(currentColor, 0.1); }
entry.busy { opacity: 0.5; }
window {
    background-image: url("file:///etc/greetd/gentoocave.png");
    background-size: cover;
    background-position: center;
}
"""


def send(sock, msg):
    data = json.dumps(msg).encode()
    sock.sendall(len(data).to_bytes(4, "little") + data)


def recv(sock):
    def readn(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("greetd socket closed")
            buf += chunk
        return buf

    return json.loads(readn(struct.unpack("<I", readn(4))[0]))


class Greeter(Gtk.Application):
    def __init__(self, username, command):
        super().__init__()
        self.username = username
        self.command = command
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(os.environ["GREETD_SOCK"])
        self._busy = True  # in-flight until first auth prompt arrives
        self.connect("activate", self.on_activate)

    def request(self, msg, callback):
        """Send a request and dispatch the response callback on the main thread."""
        send(self.sock, msg)
        threading.Thread(
            target=lambda: GLib.idle_add(callback, recv(self.sock)),
            daemon=True,
        ).start()

    def on_activate(self, _app):
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)

        self.label = Gtk.Label()
        self.label.set_visible(False)
        box.append(self.label)

        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_width_chars(30)
        self.entry.set_visible(False)
        self.entry.connect("activate", self.on_submit)
        box.append(self.entry)

        self.udev = GUdev.Client(subsystems=["usb"])
        self.udev.connect("uevent", self.on_uevent)

        win = Gtk.ApplicationWindow(application=self)
        win.set_cursor_from_name("none")
        win.set_child(box)
        win.fullscreen()
        win.present()

        self.request(
            {"type": "create_session", "username": self.username},
            self.on_auth,
        )

    def on_auth(self, resp):
        match resp:
            case {"type": "success"}:
                self.request(
                    {"type": "start_session", "cmd": self.command},
                    lambda _: self.quit(),
                )
            case {
                "type": "auth_message",
                "auth_message_type": "secret" | "visible" as kind,
            }:
                self.entry.set_visibility(kind == "visible")
                if not self.entry.get_visible():
                    self.entry.set_visible(True)
                    self.entry.grab_focus()
                self.label.set_visible(False)
                self.set_busy(False)
            case {"type": "auth_message", "auth_message": msg}:
                # info or error — display and immediately acknowledge so PAM
                # starts listening (e.g. for a FIDO2 key touch).
                self.label.set_text(msg)
                self.label.set_visible(True)
                self.entry.set_visible(False)
                self.request(
                    {"type": "post_auth_message_response", "response": ""},
                    self.on_auth,
                )
            case {"type": "error"}:
                self.restart_auth()

    def restart_auth(self):
        self.request(
            {"type": "cancel_session"},
            lambda _: self.request(
                {"type": "create_session", "username": self.username},
                self.on_auth,
            ),
        )

    def on_uevent(self, _client, action, device):
        if (
            action == "add"
            and device.get_property("DEVTYPE") == "usb_device"
            and device.get_property("ID_VENDOR_ID") == "1050"
            and not self._busy
        ):
            self._busy = True
            self.entry.set_text("")
            self.entry.set_visible(False)
            self.restart_auth()

    def set_busy(self, busy):
        self._busy = busy
        if busy:
            self.entry.add_css_class("busy")
        else:
            self.entry.remove_css_class("busy")

    def on_submit(self, entry):
        if self._busy:
            return
        password = entry.get_text()
        entry.set_text("")
        self.set_busy(True)
        self.request(
            {"type": "post_auth_message_response", "response": password},
            self.on_auth,
        )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <username> <command...>", file=sys.stderr)
        sys.exit(1)
    Greeter(sys.argv[1], sys.argv[2:]).run()
