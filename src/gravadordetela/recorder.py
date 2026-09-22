"""GStreamer capture and recoverable, lossless MP4 assembly."""

import errno
import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

Gst.init(None)


def state_root():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "gravadordetela"


def quote(value):
    # Gst.parse_launch recognizes double quotes; shell-style single quotes
    # become literal filename characters.
    return json.dumps(str(value), ensure_ascii=False)


def geometry(size, limit):
    try:
        width, height = map(int, size)
    except (TypeError, ValueError):
        width, height = 1920, 1080
    if width < 2 or height < 2:
        width, height = 1920, 1080
    if limit != "Original":
        max_width, max_height = (1920, 1080) if limit == "1080p" else (1280, 720)
        ratio = min(1.0, max_width / width, max_height / height)
        width, height = int(width * ratio), int(height * ratio)
    return max(2, width // 2 * 2), max(2, height // 2 * 2)


def encoder(fps, force_software=False):
    bitrate = 8000 if fps == 60 else 6000
    if not force_software and Gst.ElementFactory.find("vah264enc"):
        return (f"vah264enc bitrate={bitrate} key-int-max={fps * 2} target-usage=7",
                "Intel VA-API")
    if not force_software and Gst.ElementFactory.find("vaapih264enc"):
        return f"vaapih264enc bitrate={bitrate} keyframe-period={fps * 2}", "Intel VA-API"
    if Gst.ElementFactory.find("openh264enc"):
        return (f"openh264enc bitrate={bitrate * 1000} complexity=low "
                f"usage-type=screen rate-control=bitrate gop-size={fps * 2}",
                "OpenH264 (CPU)")
    if Gst.ElementFactory.find("x264enc"):
        return (f"x264enc bitrate={bitrate} speed-preset=ultrafast "
                f"tune=zerolatency key-int-max={fps * 2}", "x264 (CPU)")
    raise RuntimeError("Nenhum encoder H.264 do GStreamer está disponível.")


def pipeline_description(fd, node, properties, settings, session_dir, phase=0):
    width, height = geometry(properties.get("size"), settings["resolution"])
    fps = int(settings["fps"])
    codec, codec_name = encoder(fps, settings.get("_force_software", False))
    selector = (f"target-object={properties['pipewire-serial']}"
                if "pipewire-serial" in properties else f"path={node}")
    screen = (f"pipewiresrc name=screen fd={fd} {selector} do-timestamp=true "
              "! queue max-size-buffers=4 leaky=downstream "
              "! videoconvert ! videoscale ! videorate "
              f"! video/x-raw,width={width},height={height},framerate={fps}/1")

    camera = settings.get("camera")
    if camera:
        camera_width = max(160, (width // 5) // 2 * 2)
        camera_height = max(90, (camera_width * 9 // 16) // 2 * 2)
        xpos = width - camera_width - 24
        ypos = height - camera_height - 24
        video = (
            f"compositor name=comp background=black sink_1::xpos={xpos} "
            f"sink_1::ypos={ypos} sink_1::width={camera_width} "
            f"sink_1::height={camera_height} "
            f"! video/x-raw,width={width},height={height},framerate={fps}/1 "
            f"! videoconvert ! {codec} ! h264parse config-interval=-1 "
            "! queue ! mux.video "
            f"{screen} ! queue ! comp.sink_0 "
            f"v4l2src name=webcam device={quote(camera)} do-timestamp=true "
            "! queue max-size-buffers=2 leaky=downstream ! videoconvert "
            f"! videoscale ! video/x-raw,width={camera_width},height={camera_height} "
            "! comp.sink_1 "
        )
    else:
        video = f"{screen} ! queue ! {codec} ! h264parse config-interval=-1 ! queue ! mux.video "

    sources = [source for source in (settings.get("microphone"), settings.get("system_audio")) if source]
    audio = ""
    if sources:
        audio = (
            "audiomixer name=mix ! audioconvert ! audioresample "
            "! audio/x-raw,rate=48000,channels=2 "
            "! avenc_aac bitrate=160000 ! aacparse ! queue ! mux.audio_0 "
        )
        for index, source in enumerate(sources):
            audio += (f"pulsesrc name=audio{index} device={quote(source)} "
                      "do-timestamp=true provide-clock=false "
                      "! queue max-size-time=200000000 leaky=downstream "
                      "! audioconvert ! audioresample ! mix. ")

    location = quote(session_dir / f"part-{phase:04d}-%05d.mkv")
    mux = (f"splitmuxsink name=mux location={location} "
           "max-size-time=10000000000 send-keyframe-requests=true "
           "async-finalize=true muxer-factory=matroskamux")
    return video + audio + mux, codec_name, (width, height)


def recoverable_sessions():
    root = state_root() / "sessions"
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir()
                  if path.is_dir() and (path / "session.json").exists()
                  and list(path.glob("part-*.mkv")))


def assemble(session_dir):
    """Preserve session data unless the final MP4 was verified and moved."""
    info = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    output_dir = Path(info["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    for path in sorted(session_dir.glob("part-*.mkv")):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=15)
        if probe.returncode == 0 and path.stat().st_size > 1024:
            segments.append(path)
    if not segments:
        raise RuntimeError("Nenhum trecho íntegro foi encontrado. Os dados foram preservados.")

    manifest = session_dir / "parts.ffconcat"
    manifest.write_text(
        "ffconcat version 1.0\n" + "".join(
            "file '" + str(path).replace("'", "'\\''") + "'\n" for path in segments),
        encoding="utf-8")
    partial = session_dir / "final.partial.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(manifest),
        "-c", "copy", "-movflags", "+faststart", str(partial),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode != 0 or not partial.exists() or partial.stat().st_size < 1024:
        raise RuntimeError("Falha ao criar MP4: " + result.stderr[-600:])
    output = output_dir / info["filename"]
    if output.exists():
        output = output_dir / f"{output.stem}_{uuid.uuid4().hex[:6]}.mp4"
    try:
        os.replace(partial, output)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # A selected folder may be on another filesystem or external drive.
        destination_partial = output.with_name(output.name + ".partial")
        try:
            shutil.copyfile(partial, destination_partial)
            os.replace(destination_partial, output)
        finally:
            destination_partial.unlink(missing_ok=True)
    shutil.rmtree(session_dir)
    return output, len(segments)


class Recorder:
    def __init__(self, status, finished):
        self.status_callback = status
        self.finished_callback = finished
        self.pipeline = None
        self.bus = None
        self.bus_handler = None
        self.session_dir = None
        self.fd = None
        self.state = "idle"
        self.node = None
        self.properties = None
        self.settings = None
        self.codec_name = None
        self.retried_software = False

    def start(self, fd, node, properties, settings):
        self.retried_software = False
        self.node = node
        self.properties = properties
        self.settings = settings
        self.session_dir = state_root() / "sessions" / uuid.uuid4().hex
        self.session_dir.mkdir(parents=True, exist_ok=False)
        filename = "Gravacao_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:6] + ".mp4"
        (self.session_dir / "session.json").write_text(
            json.dumps({"output_dir": settings["output_dir"], "filename": filename},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        self._start_pipeline(fd)

    def _start_pipeline(self, fd):
        self.fd = fd
        description, codec_name, dimensions = pipeline_description(
            fd, self.node, self.properties, self.settings,
            self.session_dir, len({p.name.split("-")[1] for p in self.session_dir.glob("part-*.mkv")}))
        self.codec_name = codec_name
        try:
            self.pipeline = Gst.parse_launch(description)
            self.bus = self.pipeline.get_bus()
            self.bus.add_signal_watch()
            self.bus_handler = self.bus.connect("message", self._on_message)
            if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("Não foi possível iniciar o GStreamer.")
        except Exception:
            self._release()
            raise
        self.state = "recording"
        self.status_callback("recording", f"Gravando {dimensions[0]}×{dimensions[1]} a {self.settings['fps']} FPS · {codec_name}")

    def pause(self):
        if self.state != "recording":
            return
        self.state = "pausing"
        self.status_callback("stopping", "Pausando e fechando o trecho atual…")
        self._send_eos()

    def resume(self, fd):
        if self.state != "paused":
            os.close(fd)
            return
        self._start_pipeline(fd)

    def retry_software(self, fd):
        if self.state != "restarting":
            os.close(fd)
            return
        self._start_pipeline(fd)

    def stop(self):
        if self.state == "paused":
            self.state = "finalizing"
            self._assemble_async()
            return
        if self.state == "pausing":
            self.state = "stopping"
            self.status_callback("stopping", "Finalizando os trechos do vídeo…")
            return
        if self.state not in ("recording", "pausing"):
            return
        self.state = "stopping"
        self.status_callback("stopping", "Finalizando os trechos do vídeo…")
        self._send_eos()

    def _send_eos(self):
        names = ["screen"]
        if self.settings.get("camera"):
            names.append("webcam")
        count = sum(bool(self.settings.get(key)) for key in ("microphone", "system_audio"))
        names.extend(f"audio{index}" for index in range(count))
        for name in names:
            source = self.pipeline.get_by_name(name)
            if source:
                source.send_event(Gst.Event.new_eos())

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.ERROR:
            error, detail = message.parse_error()
            can_retry = (self.codec_name == "Intel VA-API" and
                         not self.retried_software and
                         not list(self.session_dir.glob("part-*.mkv")))
            if can_retry:
                self._release()
                self.retried_software = True
                self.settings["_force_software"] = True
                self.state = "restarting"
                self.status_callback("starting", "Aceleração indisponível; tentando pela CPU…")
                self.finished_callback(None, "retry_software")
                return
            self.status_callback("error", f"Falha na captura: {error.message}. {detail[-180:] if detail else ''}")
            self._release()
            self.state = "idle"
            self.finished_callback(None, "Os trechos recuperáveis foram preservados.")
        elif message.type == Gst.MessageType.EOS:
            self._release()
            if self.state == "pausing":
                self.state = "paused"
                self.status_callback("paused", "Gravação pausada")
            else:
                self.state = "finalizing"
                self._assemble_async()

    def _assemble_async(self):
        self.status_callback("stopping", "Montando o MP4…")
        directory = self.session_dir

        def worker():
            try:
                output, count = assemble(directory)
                GLib.idle_add(self._assembled, output, count, None)
            except Exception as exc:
                GLib.idle_add(self._assembled, None, 0, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _assembled(self, output, count, error):
        self.state = "idle"
        if error:
            self.status_callback("error", error)
            self.finished_callback(None, "Os trechos foram preservados para recuperação.")
        else:
            self.status_callback("idle", f"Vídeo salvo: {output.name} ({count} trechos)")
            self.finished_callback(output, None)
        return GLib.SOURCE_REMOVE

    def _release(self):
        if self.bus:
            self.bus.disconnect(self.bus_handler)
            self.bus.remove_signal_watch()
            self.bus = None
            self.bus_handler = None
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
