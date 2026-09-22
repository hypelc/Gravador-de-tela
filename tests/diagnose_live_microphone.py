"""Optional live microphone regression check; never captures the real screen.

Run with: PYTHONPATH=src python3 tests/diagnose_live_microphone.py
The temporary audio/video files are deleted after the check.
"""

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from gravadordetela.main import load_settings, pulse_sources
from gravadordetela.recorder import pipeline_description

Gst.init(None)


def measure(source, system_source, with_mic):
    with tempfile.TemporaryDirectory(prefix="gravadordetela-live-test-") as folder:
        settings = {
            "resolution": "1080p",
            "fps": 30,
            "microphone": source if with_mic else "",
            "system_audio": system_source,
            "camera": "",
            "output_dir": folder,
            "_force_software": True,
        }
        description, _codec, _size = pipeline_description(
            3, 42, {"size": (1920, 1080)}, settings, Path(folder))
        description = description.replace(
            "pipewiresrc name=screen fd=3 path=42 do-timestamp=true",
            "videotestsrc name=screen is-live=true pattern=ball")
        description = description.replace(
            "h264parse config-interval=-1 ! queue ! mux.video",
            "h264parse config-interval=-1 ! identity name=videomark "
            "signal-handoffs=true ! queue ! mux.video")
        pipeline = Gst.parse_launch(description)
        marks = []
        pipeline.get_by_name("videomark").connect(
            "handoff", lambda _identity, _buffer: marks.append(time.monotonic()))
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        loop = GLib.MainLoop()
        result = {"eos": False, "error": None, "clock": None}

        def on_message(_bus, message):
            if message.type == Gst.MessageType.ERROR:
                error, _details = message.parse_error()
                result["error"] = error.message
                loop.quit()
            elif message.type == Gst.MessageType.EOS:
                result["eos"] = True
                loop.quit()
            elif message.type == Gst.MessageType.NEW_CLOCK:
                clock = message.parse_new_clock()
                result["clock"] = clock.get_name() if clock else None

        bus.connect("message", on_message)
        duration = 3.0
        started = time.monotonic()
        pipeline.set_state(Gst.State.PLAYING)

        def stop():
            pipeline.get_by_name("screen").send_event(Gst.Event.new_eos())
            audio_count = int(with_mic) + int(bool(system_source))
            for index in range(audio_count):
                pipeline.get_by_name(f"audio{index}").send_event(Gst.Event.new_eos())
            return GLib.SOURCE_REMOVE

        stop_id = GLib.timeout_add(int(duration * 1000), stop)
        watchdog_id = GLib.timeout_add(int((duration + 5) * 1000),
                                       lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
        try:
            loop.run()
        finally:
            for source_id in (stop_id, watchdog_id):
                if GLib.MainContext.default().find_source_by_id(source_id):
                    GLib.source_remove(source_id)
            pipeline.set_state(Gst.State.NULL)
            bus.remove_signal_watch()

        gaps = [later - earlier for earlier, later in zip(marks, marks[1:])]
        audio_span = None
        audio_max_gap = None
        if with_mic and result["eos"]:
            timestamps = []
            for part in sorted(Path(folder).glob("part-*.mkv")):
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "packet=pts_time", "-of", "json", str(part)],
                    capture_output=True, text=True, check=True)
                timestamps.extend(float(packet["pts_time"])
                                  for packet in json.loads(probe.stdout).get("packets", [])
                                  if "pts_time" in packet)
            if timestamps:
                audio_span = round(timestamps[-1] - timestamps[0], 2)
                audio_max_gap = round(max((b - a for a, b in zip(timestamps, timestamps[1:])),
                                          default=0), 2)
        return {
            "frames": len(marks),
            "fps": round(len(marks) / duration, 1),
            "max_gap_s": round(max(gaps, default=0), 2),
            "clock": result["clock"],
            "eos": result["eos"],
            "error": result["error"],
            "elapsed_s": round(time.monotonic() - started, 2),
            "audio_span_s": audio_span,
            "audio_max_gap_s": audio_max_gap,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--system-audio", action="store_true")
    options = parser.parse_args()
    source = load_settings().get("microphone")
    if not source:
        parser.error("Selecione um microfone no aplicativo primeiro.")
    system_source = ""
    if options.system_audio:
        _microphones, monitors = pulse_sources()
        system_source = load_settings().get("system_audio") or (monitors[0][1] if monitors else "")
        if not system_source:
            parser.error("Nenhuma fonte de áudio do sistema foi encontrada.")
    baseline = measure(source, system_source, False)
    microphone = measure(source, system_source, True)
    print("sem microfone:", baseline)
    print("com microfone:", microphone)
    passed = (not microphone["error"] and microphone["eos"] and
              microphone["frames"] >= baseline["frames"] * 0.85 and
              microphone["max_gap_s"] < 0.35 and
              microphone["audio_span_s"] is not None and
              microphone["audio_span_s"] >= 2.5 and
              microphone["audio_max_gap_s"] < 0.25)
    print("resultado:", "PASSOU" if passed else "FALHOU")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
