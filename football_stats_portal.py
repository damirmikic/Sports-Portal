"""Existing football-statistics views mounted inside Sports Portal."""
from pathlib import Path
from flask import Blueprint
from source_modules import load_source_package

SOURCE_DIR = Path(r"C:\Users\dkecm\Desktop\fudbal statistika")
legacy = load_source_package("_sports_portal_football_stats", SOURCE_DIR, ("app",))
legacy.HTML = legacy.HTML.replace(
    "<body>",
    '<body><a href="/portal" style="position:fixed;top:28px;right:40px;z-index:1000;color:#f1ca45;text-decoration:none;font-weight:700">← Sports Portal</a>',
    1,
)
football_stats_bp = Blueprint("football_stats", __name__, url_prefix="/football-stats")
football_stats_bp.add_url_rule("/", "index", legacy.index)
