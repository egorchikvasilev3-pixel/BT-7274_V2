# -*- coding: utf-8 -*-
"""Временная утилита проверки связи с obs-websocket (не часть БТ)."""

import os

from obsws_python import ReqClient

CLIENT = ReqClient(
    host="localhost",
    port=4455,
    password=os.environ.get("OBS_PASSWORD", ""),
    timeout=5,
)

print("OBS version:", CLIENT.get_version().obs_version)
video = CLIENT.get_video_settings()
print("FPS:", video.fps_num, "/", video.fps_den, "canvas:", video.base_width, "x", video.base_height)
rec = CLIENT.get_record_status()
print("REC:", rec.recording, "paused:", rec.paused, "timecode:", rec.timecode)
print("RecDir:", CLIENT.get_record_directory().record_directory)
