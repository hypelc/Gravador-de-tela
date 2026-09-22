"""Local Fedora/KDE screen recorder."""

import os
from pathlib import Path

# Fedora's current GStreamer VA plugin hides the legacy i965 Intel driver by
# default. Configure it before GStreamer is imported or initialized, but keep
# explicit user overrides intact.
driver_paths = (
    Path("/usr/lib64/dri/i965_drv_video.so"),
    Path("/usr/lib/x86_64-linux-gnu/dri/i965_drv_video.so"),
    Path("/usr/lib/dri/i965_drv_video.so"),
)
if "LIBVA_DRIVER_NAME" not in os.environ and any(path.is_file() for path in driver_paths):
    os.environ["LIBVA_DRIVER_NAME"] = "i965"
if os.environ.get("LIBVA_DRIVER_NAME") == "i965":
    os.environ.setdefault("GST_VA_ALL_DRIVERS", "1")
