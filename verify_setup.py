from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RULE = ROOT / "prolog/btsg.pl"
EXPECTED_SHA256 = "98f88f8cc0a8e81b8f3301cf73542c4579023ae10038ed63e77edff83ea62ab0"

print(f"Python: {sys.version.split()[0]}")
print(f"Project: {ROOT}")
print(f"Prolog rule exists: {RULE.exists()}")
if RULE.exists():
    digest = hashlib.sha256(RULE.read_bytes()).hexdigest()
    print(f"btsg.pl SHA256: {digest}")
    print(f"Matches original rule: {digest == EXPECTED_SHA256}")

swipl = shutil.which("swipl")
print(f"SWI-Prolog found: {bool(swipl)}")
if swipl:
    version = subprocess.run([swipl, "--version"], capture_output=True, text=True).stdout.strip()
    print(version)
else:
    print("Install on macOS with Homebrew: brew install swi-prolog")
