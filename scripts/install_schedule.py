#!/usr/bin/env python3
"""Install and activate this repository's combined daily macOS LaunchAgent."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(root/'scripts/setup_schedule.py')], cwd=root, check=True)
source = root/'runs/com.literature-scout.daily.plist'
target = Path.home()/'Library/LaunchAgents'/source.name
target.parent.mkdir(parents=True, exist_ok=True)
service = f'gui/{os.getuid()}/com.literature-scout.daily'
loaded = subprocess.run(['launchctl', 'print', service], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL).returncode == 0
if loaded:
    subprocess.run(['launchctl', 'bootout', service], check=True)
shutil.copy2(source, target)
subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(target)], check=True)
print('Activated combined daily digest: 07:30 Asia/Shanghai, with five-minute retry checks.')
print('Missing credentials pause delivery; configure them locally before email can be sent.')
