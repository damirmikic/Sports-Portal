"""NFL views served by the central Flask application; no server on 5001."""
from pathlib import Path
from threading import RLock
from flask import Blueprint
from source_modules import load_source_package

SOURCE_DIR = Path(r"C:\Users\dkecm\Desktop\player props")
legacy = load_source_package(
    "_sports_portal_nfl", SOURCE_DIR,
    ("superbet", "king", "balkanbet", "merkurxtip", "fanduel",
     "euroleague_stats", "nfl_matcher", "app"),
)

# Preserve the existing layout; scope its lazy-load endpoint to the NFL module.
legacy.INDEX_HTML = legacy.INDEX_HTML.replace(
    "fetch('/api/game/'", "fetch('/nfl/api/game/'"
).replace(
    "<body>",
    '<body><a href="/portal" style="position:fixed;top:28px;right:40px;z-index:1000;color:#f1ca45;text-decoration:none;font-weight:700">← Sports Portal</a>',
    1,
)

nfl_bp = Blueprint("nfl", __name__, url_prefix="/nfl")
# The original NFL server is single-threaded; preserve that behavior for its
# collectors while the rest of Sports Portal continues to serve concurrently.
_request_lock = RLock()


@nfl_bp.route("/")
def home():
    with _request_lock:
        return legacy.home()


@nfl_bp.route("/api/game/<path:key>")
def game(key):
    with _request_lock:
        return legacy.api_game(key)


@nfl_bp.record_once
def register_filters(state):
    state.app.jinja_env.filters["odd"] = legacy.fmt_odd
