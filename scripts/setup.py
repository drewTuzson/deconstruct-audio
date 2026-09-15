#!/usr/bin/env python3
"""Install runtime dependencies into this skill's private environment."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import venv

root = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 10):
    sys.exit('Python 3.10 or newer is required.')
missing = [x for x in ('ffmpeg', 'ffprobe') if not shutil.which(x)]
if missing:
    sys.exit('Missing ' + ', '.join(missing) + '. See references/onboarding.md.')
env = root / '.venv'
venv.EnvBuilder(with_pip=True).create(env)
python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')], check=True)
print('DEPENDENCIES_READY')
print('Next: run scripts/deconstruct.py doctor with the private environment Python.')
