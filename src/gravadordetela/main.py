"""Minimal GTK controls for the Fedora/KDE screen recorder."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst, Gtk, Pango

from .portal import Portal
from .recorder import Recorder, assemble, encoder, recoverable_sessions
from .tray import Tray


APP_ID = "io.github.jeanlc77.GravadorDeTela"
AUTOSTART_NAME = APP_ID + ".desktop"


def settings_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gravadordetela" / "settings.json"


def default_folder():
    videos = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS)
    return str(Path(videos or Path.home() / "Videos") / "Gravador de Tela")


def load_settings():
    defaults = {
        "output_dir": default_folder(), "resolution": "1080p", "fps": 30,
        "microphone": "", "system_audio": "", "camera": "", "autostart": True,
    }
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return {**defaults, **{key: data[key] for key in defaults if key in data}}
    except (OSError, json.JSONDecodeError):
        return defaults


def pulse_sources():
    try:
        result = subprocess.run(
            ["pactl", "-f", "json", "list", "sources"], capture_output=True,
            text=True, timeout=5, check=True)
        sources = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return [], []
    microphones, system = [], []
    for source in sources:
        name = source.get("name", "")
        if not name:
            continue
        label = source.get("description") or name
        (system if name.endswith(".monitor") else microphones).append((label, name))
    return microphones, system


def cameras():
    result = []
    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Video/Source", None)
    if monitor.start():
        try:
            for device in monitor.get_devices():
                properties = device.get_properties()
                path = properties.get_string("api.v4l2.path") if properties else None
                if path and Path(path).exists():
                    result.append((device.get_display_name(), path))
        finally:
            monitor.stop()
    return result


class App(Gtk.Application):
    def __init__(self, background=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.background = background
        self.settings = load_settings()
        self.portal = Portal()
        self.recorder = Recorder(self.set_status, self.recording_finished)
        self.session = None
        self.window = None
        self.tray = None
        self.exit_when_done = False
        self.initializing = False
        self.options = {}

    def do_activate(self):
        if self.window:
            self.window.present()
            return
        self.hold()  # keep hotkeys and tray alive after the window is closed
        self._build_window()
        Path(self.settings["output_dir"]).mkdir(parents=True, exist_ok=True)
        self._save()
        self.tray = Tray(self.present_window)
        self.portal.shortcuts(self.shortcut, self.shortcut_status)
        if not self.background:
            self.window.present()
        self._refresh_recovery()

    def _build_window(self):
        self.initializing = True
        self.window = Gtk.ApplicationWindow(application=self, title="Gravador de Tela")
        self.window.set_default_size(480, 590)
        self.window.connect("close-request", self._on_close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        root.set_margin_top(20)
        root.set_margin_bottom(20)
        root.set_margin_start(22)
        root.set_margin_end(22)
        self.window.set_child(root)

        heading = Gtk.Label(label="Gravador de Tela", xalign=0)
        heading.add_css_class("title-1")
        root.append(heading)
        root.append(Gtk.Label(label="Escolha os dispositivos e a qualidade antes de gravar.", xalign=0))

        self._row(root, "Monitor", Gtk.Label(label="Escolher no diálogo do KDE ao iniciar", xalign=0))
        self._dropdown(root, "Microfone", "microphone")
        self._dropdown(root, "Áudio do sistema", "system_audio")
        self._dropdown(root, "Webcam", "camera")

        refresh = Gtk.Button(label="Atualizar dispositivos")
        refresh.connect("clicked", lambda _button: self._refresh_devices())
        root.append(refresh)

        quality = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        resolution = Gtk.DropDown.new_from_strings(["Original", "1080p", "720p"])
        resolution.set_selected(["Original", "1080p", "720p"].index(self.settings["resolution"])
                              if self.settings["resolution"] in ("Original", "1080p", "720p") else 1)
        resolution.connect("notify::selected", self._choice_changed, "resolution")
        self.options["resolution"] = resolution
        quality.append(Gtk.Label(label="Resolução"))
        quality.append(resolution)
        fps = Gtk.DropDown.new_from_strings(["30 FPS", "60 FPS"])
        fps.set_selected(1 if self.settings["fps"] == 60 else 0)
        fps.connect("notify::selected", self._choice_changed, "fps")
        self.options["fps"] = fps
        quality.append(Gtk.Label(label="Quadros"))
        quality.append(fps)
        root.append(quality)
        self.quality_note = Gtk.Label(xalign=0)
        self.quality_note.set_wrap(True)
        self.quality_note.add_css_class("dim-label")
        root.append(self.quality_note)

        folder_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.folder_label = Gtk.Label(label=self.settings["output_dir"], xalign=0)
        self.folder_label.set_hexpand(True)
        self.folder_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        folder_row.append(self.folder_label)
        folder_button = Gtk.Button(label="Pasta…")
        folder_button.connect("clicked", self._choose_folder)
        folder_row.append(folder_button)
        self._row(root, "Salvar em", folder_row)

        self.autostart = Gtk.CheckButton(label="Iniciar com a sessão (fica na bandeja)")
        self.autostart.set_active(bool(self.settings["autostart"]))
        self.autostart.connect("toggled", self._autostart_changed)
        root.append(self.autostart)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.dot = Gtk.Label()
        status_row.append(self.dot)
        self.status_label = Gtk.Label(label="Pronto para gravar", xalign=0)
        self.status_label.set_wrap(True)
        self.status_label.set_hexpand(True)
        status_row.append(self.status_label)
        root.append(status_row)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.start_button = Gtk.Button(label="Iniciar gravação")
        self.start_button.add_css_class("suggested-action")
        self.start_button.set_hexpand(True)
        self.start_button.connect("clicked", lambda _button: self.start_or_pause())
        actions.append(self.start_button)
        self.stop_button = Gtk.Button(label="Terminar e salvar")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", lambda _button: self.stop())
        actions.append(self.stop_button)
        root.append(actions)

        self.recover_button = Gtk.Button(label="Recuperar gravação interrompida")
        self.recover_button.connect("clicked", self._recover)
        self.recover_button.set_visible(False)
        root.append(self.recover_button)

        self.shortcut_label = Gtk.Label(label="Atalhos sugeridos: Ctrl+Shift+F9 · Ctrl+Shift+F10", xalign=0)
        self.shortcut_label.add_css_class("dim-label")
        root.append(self.shortcut_label)
        exit_button = Gtk.Button(label="Sair")
        exit_button.connect("clicked", self._exit)
        root.append(exit_button)

        self._refresh_devices()
        self.initializing = False
        self._update_quality_note()
        self.set_status("idle", "Pronto para gravar")

    def _row(self, parent, title, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("heading")
        row.append(label)
        row.append(widget)
        parent.append(row)

    def _dropdown(self, parent, title, key):
        dropdown = Gtk.DropDown.new_from_strings(["Desativado"])
        dropdown.set_hexpand(True)
        dropdown.connect("notify::selected", self._choice_changed, key)
        self.options[key] = dropdown
        self._row(parent, title, dropdown)

    def _set_dropdown(self, key, choices):
        dropdown = self.options[key]
        self.options[key + "_values"] = [""] + [value for _label, value in choices]
        labels = ["Desativado"] + [label for label, _value in choices]
        dropdown.set_model(Gtk.StringList.new(labels))
        values = self.options[key + "_values"]
        if self.settings[key] not in values:
            self.settings[key] = ""
        dropdown.set_selected(values.index(self.settings[key]) if self.settings[key] in values else 0)

    def _refresh_devices(self):
        previous = self.initializing
        self.initializing = True
        microphones, system = pulse_sources()
        self._set_dropdown("microphone", microphones)
        self._set_dropdown("system_audio", system)
        self._set_dropdown("camera", cameras())
        self.initializing = previous
        if not previous:
            self._save()

    def _choice_changed(self, dropdown, _param, key):
        if self.initializing:
            return
        selected = dropdown.get_selected()
        if key == "fps":
            self.settings[key] = 60 if selected == 1 else 30
        elif key == "resolution":
            self.settings[key] = ["Original", "1080p", "720p"][selected]
        else:
            self.settings[key] = self.options[key + "_values"][selected]
        self._save()
        if key in ("fps", "resolution"):
            self._update_quality_note()

    def _update_quality_note(self):
        try:
            _pipeline, name = encoder(int(self.settings["fps"]))
        except RuntimeError as exc:
            self.quality_note.set_text(str(exc))
            return
        if self.settings["fps"] == 60 and name.endswith("(CPU)"):
            self.quality_note.set_text("60 FPS na CPU pode perder quadros neste computador. Teste antes de usar.")
        else:
            self.quality_note.set_text("Codificação disponível: " + name)

    def _choose_folder(self, _button):
        dialog = Gtk.FileDialog(title="Escolha a pasta dos vídeos")

        def chosen(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
                path = folder.get_path()
                if path:
                    Path(path).mkdir(parents=True, exist_ok=True)
                    self.settings["output_dir"] = path
                    self.folder_label.set_text(path)
                    self._save()
            except GLib.Error:
                pass

        dialog.select_folder(self.window, None, chosen)

    def _autostart_changed(self, check):
        if not self.initializing:
            self.settings["autostart"] = check.get_active()
            self._save()

    def _save(self):
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.environ.get("FLATPAK_ID") == APP_ID:
            autostart = Path.home() / ".config" / "autostart" / AUTOSTART_NAME
            launch = f"flatpak run {APP_ID} --background"
        else:
            autostart = path.parent.parent / "autostart" / AUTOSTART_NAME
            launch = "/usr/bin/gravadordetela --background"
        if self.settings["autostart"] and (os.environ.get("FLATPAK_ID") == APP_ID
                                           or Path("/usr/bin/gravadordetela").exists()):
            autostart.parent.mkdir(parents=True, exist_ok=True)
            autostart.write_text(
                "[Desktop Entry]\nType=Application\nName=Gravador de Tela\n"
                f"Exec={launch}\n"
                "Icon=io.github.jeanlc77.GravadorDeTela\nX-GNOME-Autostart-enabled=true\n",
                encoding="utf-8")
        elif autostart.exists() and not self.settings["autostart"]:
            autostart.unlink()

    def present_window(self):
        self.window.present()

    def _on_close(self, _window):
        self.window.hide()
        return True

    def shortcut(self, shortcut_id):
        if shortcut_id == "record_pause":
            self.start_or_pause()
        elif shortcut_id == "stop":
            self.stop()

    def shortcut_status(self, message):
        self.shortcut_label.set_text(message)

    def start_or_pause(self):
        if self.recorder.state == "recording":
            self.recorder.pause()
            return
        if self.recorder.state == "paused":
            self.set_status("starting", "Retomando a captura…")

            def opened(fd, error):
                if error:
                    self.set_status("paused", "Não foi possível retomar: " + error)
                    return
                try:
                    self.recorder.resume(fd)
                except Exception as exc:
                    self.set_status("paused", "Não foi possível retomar: " + str(exc))

            self.portal.open_screen_remote(self.session, opened)
            return
        if self.recorder.state != "idle" or self.session:
            return
        self.settings["output_dir"] = str(Path(self.settings["output_dir"]).expanduser())
        try:
            Path(self.settings["output_dir"]).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.set_status("error", f"Pasta de destino indisponível: {exc}")
            return
        self._save()
        self.recorder.state = "starting"
        self.set_status("starting", "Escolha o monitor no diálogo do KDE…")

        def selected(session, node, remote, error):
            if error:
                self.recorder.state = "idle"
                self.set_status("error", error)
                return
            self.session = session
            fd, properties = remote
            try:
                self.recorder.start(fd, node, properties, self.settings.copy())
            except Exception as exc:
                self.portal.close_session(self.session)
                self.session = None
                self.recorder.state = "idle"
                self.set_status("error", f"Não foi possível iniciar: {exc}")
                self._refresh_recovery()

        self.portal.screen_session(selected)

    def stop(self):
        self.recorder.stop()

    def set_status(self, state, message):
        if not self.window:
            return
        colors = {
            "idle": "#6b7280", "starting": "#3b82f6", "recording": "#e01b24",
            "paused": "#e5a50a", "stopping": "#3b82f6", "error": "#e01b24",
        }
        self.dot.set_markup(f"<span foreground='{colors.get(state, '#6b7280')}' size='x-large'>●</span>")
        self.status_label.set_text(message)
        if self.tray:
            self.tray.update(state)
        self.start_button.set_label("Pausar" if state == "recording" else
                                    "Retomar" if state == "paused" else "Iniciar gravação")
        self.start_button.set_sensitive(state in ("idle", "error", "recording", "paused"))
        self.stop_button.set_sensitive(state in ("recording", "paused"))

    def recording_finished(self, output, error):
        if error == "retry_software" and self.session:
            def opened(fd, fd_error):
                if fd_error:
                    self.portal.close_session(self.session)
                    self.session = None
                    self.recorder.state = "idle"
                    self.set_status("error", "Falha ao usar CPU: " + fd_error)
                    return
                try:
                    self.recorder.retry_software(fd)
                except Exception as exc:
                    self.portal.close_session(self.session)
                    self.session = None
                    self.recorder.state = "idle"
                    self.set_status("error", "Falha ao usar CPU: " + str(exc))

            self.portal.open_screen_remote(self.session, opened)
            return
        if self.session:
            self.portal.close_session(self.session)
            self.session = None
        self._refresh_recovery()
        if self.exit_when_done:
            self.quit()

    def _refresh_recovery(self):
        sessions = recoverable_sessions()
        self.recover_button.set_visible(bool(sessions))
        if sessions:
            self.recover_button.set_label(f"Recuperar gravação interrompida ({len(sessions)})")

    def _recover(self, _button):
        sessions = recoverable_sessions()
        if not sessions or self.recorder.state != "idle":
            return
        self.recover_button.set_sensitive(False)
        self.set_status("stopping", "Tentando recuperar os trechos íntegros…")

        def worker():
            try:
                output, count = assemble(sessions[0])
                GLib.idle_add(done, f"Recuperado: {output.name} ({count} trechos)")
            except Exception as exc:
                GLib.idle_add(done, f"Recuperação falhou: {exc}")

        def done(message):
            self.set_status("error" if message.startswith("Recuperação falhou") else "idle", message)
            self.recover_button.set_sensitive(True)
            self._refresh_recovery()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=worker, daemon=True).start()

    def _exit(self, _button):
        if self.recorder.state in ("recording", "paused", "pausing"):
            self.exit_when_done = True
            self.recorder.stop()
        elif self.recorder.state in ("starting", "stopping", "finalizing"):
            self.exit_when_done = True
        else:
            self.quit()


def main():
    background = "--background" in sys.argv
    args = [arg for arg in sys.argv if arg != "--background"]
    return App(background=background).run(args)
