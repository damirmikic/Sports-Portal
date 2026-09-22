"""Run all player-points bookmaker refreshers in sequence."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

# Both feeds now pass through the same canonical roster before reaching the
# shared database and portal.
ACTIVE_UPDATERS = [
    "euroleague_1xbet_updater.py",
    "superbet_player_points_updater.py",
]

# Meridian is enabled automatically once its short-lived access token is
# supplied. This keeps the existing refresh safe when the bookmaker session
# is not open, while allowing the same one-command refresh to include it.
if os.getenv("MERIDIAN_ACCESS_TOKEN", "").strip():
    ACTIVE_UPDATERS.append("meridian_player_points_updater.py")

failures = []
for name in ACTIVE_UPDATERS:
    result = subprocess.run([sys.executable, str(ROOT / name)], cwd=str(ROOT), check=False)
    if result.returncode:
        failures.append(name)

if failures:
    raise SystemExit("Neuspešan refresh: " + ", ".join(failures))
