#!/bin/bash
if [ -f "video_editor_bot_v39_ULTRA.py.gz" ] && [ ! -f "video_editor_bot_v39_ULTRA.py" ]; then
    gzip -dk video_editor_bot_v39_ULTRA.py.gz
fi
python video_editor_bot_v39_ULTRA.py
