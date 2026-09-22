"""End-to-end media test without taking over the user's actual screen."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from gravadordetela.recorder import assemble, encoder, geometry, pipeline_description

Gst.init(None)


class MediaTest(unittest.TestCase):
    def test_intel_encoder_produces_decodable_1080p_video(self):
        if not Gst.ElementFactory.find("vah264enc"):
            self.skipTest("VA-API H.264 encoder unavailable on this system")
        codec, name = encoder(30)
        self.assertEqual(name, "Intel VA-API")
        self.assertIn("target-usage=7", codec)
        with tempfile.TemporaryDirectory(prefix="gravadordetela-vaapi-") as temp:
            output = Path(temp) / "sample.mkv"
            description = (
                "videotestsrc num-buffers=60 pattern=ball is-live=true ! "
                "video/x-raw,width=1920,height=1080,framerate=30/1 ! "
                f"videoconvert ! {codec} ! h264parse ! queue ! mux. "
                "audiotestsrc num-buffers=96 is-live=true wave=sine ! "
                "audioconvert ! audioresample ! "
                "audio/x-raw,rate=48000,channels=2 ! "
                "avenc_aac bitrate=160000 ! aacparse ! queue ! mux. "
                "matroskamux name=mux ! "
                f'filesink location="{output}"'
            )
            pipeline = Gst.parse_launch(description)
            bus = pipeline.get_bus()
            try:
                self.assertNotEqual(pipeline.set_state(Gst.State.PLAYING),
                                    Gst.StateChangeReturn.FAILURE)
                message = bus.timed_pop_filtered(
                    15 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
                self.assertIsNotNone(message)
                if message.type == Gst.MessageType.ERROR:
                    error, detail = message.parse_error()
                    self.fail(f"VA-API encoding: {error.message}: {detail}")
            finally:
                pipeline.set_state(Gst.State.NULL)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_name,width,height", "-of", "json", str(output)],
                capture_output=True, text=True, check=True)
            streams = json.loads(probe.stdout)["streams"]
            self.assertIn({"codec_name": "h264", "width": 1920, "height": 1080}, streams)
            self.assertIn({"codec_name": "aac"}, streams)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
                capture_output=True, text=True, check=True)

    def test_intel_encoder_is_available_without_manual_environment_setup(self):
        if not Path("/usr/lib64/dri/i965_drv_video.so").is_file():
            self.skipTest("Intel i965 VA-API driver unavailable on this system")
        env = os.environ.copy()
        env.pop("LIBVA_DRIVER_NAME", None)
        env.pop("GST_VA_ALL_DRIVERS", None)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        code = (
            "from pathlib import Path; "
            "from gravadordetela.recorder import pipeline_description; "
            "settings = {'resolution': '1080p', 'fps': 30, "
            "'microphone': '', 'system_audio': '', 'camera': '', "
            "'output_dir': '/tmp'}; "
            "description, codec, size = pipeline_description("
            "3, 42, {'size': (1920, 1080), 'pipewire-serial': 123}, "
            "settings, Path('/tmp/test-gravador')); "
            "print(codec)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], env=env,
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "Intel VA-API")

    def test_uses_current_vaapi_encoder_when_available(self):
        if not Gst.ElementFactory.find("vah264enc"):
            self.skipTest("VA-API H.264 encoder unavailable on this system")
        settings = {
            "resolution": "1080p", "fps": 30, "microphone": "",
            "system_audio": "", "camera": "", "output_dir": "/tmp",
        }
        description, codec, _size = pipeline_description(
            3, 42, {"size": (1920, 1080), "pipewire-serial": 123}, settings,
            Path("/tmp/test-gravador"))
        self.assertEqual(codec, "Intel VA-API")
        self.assertIn("vah264enc bitrate=6000 key-int-max=60", description)
        pipeline = Gst.parse_launch(description)
        pipeline.set_state(Gst.State.NULL)

    def test_geometry_and_pipeline(self):
        self.assertEqual(geometry((2560, 1440), "1080p"), (1920, 1080))
        self.assertEqual(geometry((1280, 800), "1080p"), (1280, 800))
        settings = {
            "resolution": "1080p", "fps": 30, "microphone": "",
            "system_audio": "", "camera": "/dev/video0", "output_dir": "/tmp",
        }
        description, _codec, _size = pipeline_description(
            3, 42, {"size": (1920, 1080), "pipewire-serial": 123}, settings,
            Path("/tmp/test-gravador"))
        pipeline = Gst.parse_launch(description)
        self.assertEqual(pipeline.get_by_name("screen").get_property("target-object"), "123")
        self.assertEqual(pipeline.get_by_name("mux").get_property("location"),
                         "/tmp/test-gravador/part-0000-%05d.mkv")
        pipeline.set_state(Gst.State.NULL)

    def test_segments_pause_and_mp4(self):
        with tempfile.TemporaryDirectory(prefix="gravadordetela-test-") as temp:
            folder = Path(temp)
            session = folder / "session"
            session.mkdir()
            (session / "session.json").write_text(json.dumps({
                "output_dir": str(folder), "filename": "capture.mp4",
            }), encoding="utf-8")
            codec, _name = encoder(15, force_software=True)
            for phase in range(2):
                description = (
                    "videotestsrc name=video is-live=true pattern=ball ! "
                    "video/x-raw,width=320,height=180,framerate=15/1 ! "
                    f"videoconvert ! {codec} ! "
                    "h264parse ! queue ! mux.video "
                    "audiotestsrc name=audio is-live=true wave=sine ! audioconvert ! "
                    "avenc_aac bitrate=128000 ! aacparse ! queue ! mux.audio_0 "
                    f'splitmuxsink name=mux location="{session}/part-{phase:04d}-%05d.mkv" '
                    "max-size-time=10000000000 "
                    "send-keyframe-requests=true async-finalize=true "
                    "muxer-factory=matroskamux"
                )
                pipeline = Gst.parse_launch(description)
                bus = pipeline.get_bus()
                try:
                    self.assertNotEqual(pipeline.set_state(Gst.State.PLAYING),
                                        Gst.StateChangeReturn.FAILURE)
                    time.sleep(1.1)
                    pipeline.get_by_name("video").send_event(Gst.Event.new_eos())
                    pipeline.get_by_name("audio").send_event(Gst.Event.new_eos())
                    message = bus.timed_pop_filtered(
                        15 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
                    self.assertIsNotNone(message)
                    if message.type == Gst.MessageType.ERROR:
                        error, detail = message.parse_error()
                        self.fail(f"GStreamer: {error.message}: {detail}")
                finally:
                    pipeline.set_state(Gst.State.NULL)
                if phase == 0:
                    time.sleep(0.7)
            output, count = assemble(session)
            self.assertGreaterEqual(count, 1)
            self.assertTrue(output.exists())
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type:format=duration", "-of", "json", str(output)],
                capture_output=True, text=True, check=True)
            details = json.loads(probe.stdout)
            self.assertEqual({s["codec_type"] for s in details["streams"]},
                             {"video", "audio"})
            duration = float(details["format"]["duration"])
            self.assertGreater(duration, 1.5)
            self.assertLess(duration, 3.0)  # pause time is excluded

    def test_webcam_overlay_pipeline(self):
        with tempfile.TemporaryDirectory(prefix="gravadordetela-camera-") as temp:
            output = Path(temp) / "camera.mkv"
            codec, _name = encoder(15, force_software=True)
            description = (
                "compositor name=comp sink_1::xpos=220 sink_1::ypos=120 "
                "sink_1::width=80 sink_1::height=45 "
                "! video/x-raw,width=320,height=180,framerate=15/1 "
                f"! videoconvert ! {codec} ! h264parse ! matroskamux ! "
                f'filesink location="{output}" '
                "videotestsrc name=screen is-live=true pattern=ball ! "
                "video/x-raw,width=320,height=180,framerate=15/1 ! comp.sink_0 "
                "videotestsrc name=webcam is-live=true pattern=smpte ! "
                "videoconvert ! videoscale ! "
                "video/x-raw,width=80,height=45,framerate=15/1 ! comp.sink_1"
            )
            pipeline = Gst.parse_launch(description)
            bus = pipeline.get_bus()
            try:
                self.assertNotEqual(pipeline.set_state(Gst.State.PLAYING),
                                    Gst.StateChangeReturn.FAILURE)
                time.sleep(0.8)
                pipeline.get_by_name("screen").send_event(Gst.Event.new_eos())
                pipeline.get_by_name("webcam").send_event(Gst.Event.new_eos())
                message = bus.timed_pop_filtered(
                    10 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
                self.assertIsNotNone(message)
                if message.type == Gst.MessageType.ERROR:
                    error, detail = message.parse_error()
                    self.fail(f"Webcam pipeline: {error.message}: {detail}")
            finally:
                pipeline.set_state(Gst.State.NULL)
            self.assertGreater(output.stat().st_size, 1024)


if __name__ == "__main__":
    unittest.main()
