import sys
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

class MyWindow(Gtk.ApplicationWindow):
    def __init__(self, **kargs):
        super().__init__(**kargs, title="Hello World")

        self.button = Gtk.Button(label="Click Here")
        self.button.connect("clicked", self.on_button_clicked)
        self.set_child(self.button)

    def on_button_clicked(self, _widget):
        self.close()

class MyApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.example.MyGtkApplication")
        GLib.set_application_name("My Gtk Application")

    def do_activate(self):
        win = MyWindow(application=app)
        win.present()


if __name__ == "__main__":
    app = MyApplication()
    app.run(sys.argv)
