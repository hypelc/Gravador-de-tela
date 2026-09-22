"""Small asynchronous client for the desktop portals used by the recorder."""

import uuid

from gi.repository import Gio, GLib


BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"


def value(signature, data):
    return GLib.Variant(signature, data)


def unpack(data):
    if isinstance(data, GLib.Variant):
        return unpack(data.unpack())
    if isinstance(data, dict):
        return {key: unpack(item) for key, item in data.items()}
    if isinstance(data, (list, tuple)):
        return type(data)(unpack(item) for item in data)
    return data


class Portal:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def request(self, interface, method, signature, arguments, callback):
        """Call a portal method, then deliver its Request.Response asynchronously."""
        token = "grava_" + uuid.uuid4().hex
        options = dict(arguments[-1])
        options["handle_token"] = value("s", token)
        arguments = (*arguments[:-1], options)
        finished = False
        subscription = None

        def finish(result=None, error=None):
            nonlocal finished
            if finished:
                return
            finished = True
            self.bus.signal_unsubscribe(subscription)
            callback(result, error)

        def response(_bus, _sender, object_path, _iface, _signal, params):
            if not object_path.endswith("/" + token):
                return
            status, results = unpack(params)
            if status == 0:
                finish(results, None)
            elif status == 1:
                finish(None, "Operação cancelada no diálogo do sistema.")
            else:
                finish(None, "O portal do sistema recusou a operação.")

        subscription = self.bus.signal_subscribe(
            BUS, "org.freedesktop.portal.Request", "Response", None, None,
            Gio.DBusSignalFlags.NONE, response)

        def called(connection, result):
            try:
                connection.call_finish(result)
            except GLib.Error as exc:
                finish(None, str(exc))

        self.bus.call(
            BUS, PATH, interface, method, value(signature, arguments),
            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, 30000,
            None, called)

    def open_screen_remote(self, session, callback):
        """Return the file descriptor of the portal's restricted PipeWire remote."""
        def called(connection, result):
            try:
                reply, fd_list = connection.call_with_unix_fd_list_finish(result)
                index = reply.unpack()[0]
                callback(fd_list.get(index), None)
            except (GLib.Error, OSError) as exc:
                callback(None, str(exc))

        self.bus.call_with_unix_fd_list(
            BUS, PATH, "org.freedesktop.portal.ScreenCast",
            "OpenPipeWireRemote", value("(oa{sv})", (session, {})),
            GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE,
            30000, None, None, called)

    def close_session(self, session):
        if not session:
            return
        self.bus.call(
            BUS, session, "org.freedesktop.portal.Session", "Close", None,
            None, Gio.DBusCallFlags.NONE, 5000, None, None)

    def screen_session(self, callback):
        iface = "org.freedesktop.portal.ScreenCast"

        def created(result, error):
            if error:
                callback(None, None, None, error)
                return
            session = result["session_handle"]
            options = {
                "types": value("u", 1),  # one monitor, selected by the user
                "multiple": value("b", False),
                "cursor_mode": value("u", 2),  # embedded cursor
            }

            def selected(_result, select_error):
                if select_error:
                    self.close_session(session)
                    callback(None, None, None, select_error)
                    return

                def started(start_result, start_error):
                    if start_error:
                        self.close_session(session)
                        callback(None, None, None, start_error)
                        return
                    streams = start_result.get("streams", [])
                    if len(streams) != 1:
                        self.close_session(session)
                        callback(None, None, None,
                                 "Selecione exatamente um monitor.")
                        return
                    node, properties = streams[0]

                    def opened(fd, fd_error):
                        if fd_error:
                            self.close_session(session)
                        callback(session if not fd_error else None,
                                 node, (fd, properties) if fd is not None else None,
                                 fd_error)

                    self.open_screen_remote(session, opened)

                self.request(iface, "Start", "(osa{sv})",
                             (session, "", {}), started)

            self.request(iface, "SelectSources", "(oa{sv})",
                         (session, options), selected)

        self.request(iface, "CreateSession", "(a{sv})",
                     ({"session_handle_token": value("s", "grava_" + uuid.uuid4().hex)},),
                     created)

    def shortcuts(self, activated, status):
        iface = "org.freedesktop.portal.GlobalShortcuts"

        def on_activated(_bus, _sender, _path, _iface, _signal, params):
            session, shortcut_id, _timestamp, _options = unpack(params)
            if session == self.shortcut_session:
                activated(shortcut_id)

        self.bus.signal_subscribe(
            BUS, iface, "Activated", PATH, None,
            Gio.DBusSignalFlags.NONE, on_activated)

        def created(result, error):
            if error:
                status("Atalhos indisponíveis: " + error)
                return
            self.shortcut_session = result["session_handle"]
            shortcuts = [
                ("record_pause", {
                    "description": value("s", "Gravador de Tela: iniciar ou pausar"),
                    "preferred_trigger": value("s", "CTRL+SHIFT+F9"),
                }),
                ("stop", {
                    "description": value("s", "Gravador de Tela: terminar e salvar"),
                    "preferred_trigger": value("s", "CTRL+SHIFT+F10"),
                }),
            ]

            def bound(_result, bind_error):
                if bind_error:
                    status("Atalhos não configurados: " + bind_error)
                else:
                    status("Atalhos globais configurados no KDE")

            self.request(iface, "BindShortcuts", "(oa(sa{sv})sa{sv})",
                         (self.shortcut_session, shortcuts, "", {}), bound)

        self.request(iface, "CreateSession", "(a{sv})",
                     ({"session_handle_token": value("s", "grava_" + uuid.uuid4().hex)},),
                     created)
