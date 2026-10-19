#!/bin/bash
# Pi test launcher: keep the installed working directory and speech settings.
set -e
cd /home/pi/wire-pod/chipper
source ./source.sh
export LD_LIBRARY_PATH="/root/.vosk/libvosk:${LD_LIBRARY_PATH:-}"
exec /home/pi/vector-live-build/chipper/chipper-audiotap
