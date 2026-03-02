#!/usr/bin/env bash
set -euo pipefail
cd /home/deck/SteamDeckControlRemap
exec /usr/bin/konsole --hold -e /usr/bin/python3 /home/deck/SteamDeckControlRemap/tools/deck_input_monitor_hidraw.py
