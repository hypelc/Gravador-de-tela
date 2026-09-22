"""KDE StatusNotifierItem: a light system tray recording indicator."""

from gi.repository import Gio, GLib


XML = """<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(ii)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg type="s"/></signal>
    <signal name="NewTitle"/>
  </interface>
</node>"""


class Tray:
    def __init__(self, present):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.present = present
        self.icon = "io.github.jeanlc77.GravadorDeTela"
        self.title = "Gravador de Tela"
        self.status = "Active"
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        self.bus.register_object(
            "/StatusNotifierItem", node.interfaces[0],
            self._method, self._property, None)
        self.bus.call(
            "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
            "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self.bus.get_unique_name(),)),
            None, Gio.DBusCallFlags.NONE, 5000, None, self._registered)

    def _registered(self, connection, result):
        try:
            connection.call_finish(result)
        except GLib.Error:
            pass  # Recording still works if the tray is not present.

    def _method(self, _connection, _sender, _path, _interface, _method, _params, invocation):
        self.present()
        invocation.return_value(None)

    def _property(self, _connection, _sender, _path, _interface, name):
        properties = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "gravadordetela"),
            "Title": GLib.Variant("s", self.title),
            "Status": GLib.Variant("s", self.status),
            "IconName": GLib.Variant("s", self.icon),
            "ToolTip": GLib.Variant("(sa(ii)ss)", (self.icon, [], self.title, "Clique para abrir")),
            "ItemIsMenu": GLib.Variant("b", False),
        }
        return properties.get(name)

    def update(self, state):
        self.icon = {
            "recording": "io.github.jeanlc77.GravadorDeTela-recording",
            "paused": "io.github.jeanlc77.GravadorDeTela-paused",
        }.get(state, "io.github.jeanlc77.GravadorDeTela")
        self.title = {
            "recording": "● Gravando",
            "paused": "● Pausado",
            "stopping": "Finalizando vídeo",
        }.get(state, "Gravador de Tela")
        self.bus.emit_signal(None, "/StatusNotifierItem",
                             "org.kde.StatusNotifierItem", "NewIcon", None)
        self.bus.emit_signal(None, "/StatusNotifierItem",
                             "org.kde.StatusNotifierItem", "NewTitle", None)
