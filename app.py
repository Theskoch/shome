import json
import mimetypes
import os
import sys
import threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "_pydeps"))

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from ldap3 import Connection, Server


def env_path(name: str, default: Path) -> Path:
    """Read a path from the environment, falling back to the legacy layout."""
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


APP_DATA_DIR = env_path("SHOME_APP_DATA_DIR", BASE_DIR / "App_Data")
UPLOADS_DIR = env_path("SHOME_UPLOADS_DIR", BASE_DIR / "uploads")
SERVICES_FILE = APP_DATA_DIR / "services.json"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
LDAP_CONFIG_FILE = env_path("SHOME_LDAP_CONFIG", APP_DATA_DIR / "ldap_config.json")

# Only assets/ is served as static. Pointing this at BASE_DIR would expose
# app.py, App_Data/ldap_config.json and .git/ to unauthenticated requests.
app = Flask(__name__, static_folder=str(BASE_DIR / "assets"), static_url_path="/assets")
_uploads_name_map_cache: Optional[Dict[str, str]] = None

# Uploads are served back from our own origin, so anything that a browser can
# execute (.html, .svg with script, .php on a future host) is off the table.
ALLOWED_UPLOAD_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".ico", ".tiff", ".tif", ".avif", ".heic", ".heif",
}

# Login throttling: LOGIN_MAX_ATTEMPTS failures from one client, then a
# LOGIN_BLOCK_MINUTES pause, then a fresh batch of attempts. Keeps LDAP
# brute-force from tripping Active Directory account lockout policies.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("SHOME_LOGIN_MAX_ATTEMPTS", "10"))
LOGIN_BLOCK_MINUTES = int(os.environ.get("SHOME_LOGIN_BLOCK_MINUTES", "5"))

# Number of reverse proxies in front of us (Nginx Proxy Manager => 1).
# ProxyFix reads the entry *our* proxy appended to X-Forwarded-For, counting
# from the right. Parsing the header by hand and taking the first entry would
# be spoofable: the left-hand entries come from the client.
TRUSTED_PROXY_HOPS = int(os.environ.get("SHOME_TRUST_PROXY", "0"))
if TRUSTED_PROXY_HOPS > 0:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_HOPS,
        x_proto=TRUSTED_PROXY_HOPS,
        x_host=TRUSTED_PROXY_HOPS,
    )

# Session cookie over HTTPS only. Safe to enable behind a TLS-terminating
# proxy; leave off when the portal is opened by plain http://ip:port.
if os.environ.get("SHOME_SECURE_COOKIES", "0") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Cap uploads so a stray multi-gigabyte file cannot fill the data volume.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("SHOME_MAX_UPLOAD_MB", "25")) * 1024 * 1024

# State is in-memory, so the app must run in a single process (see gunicorn
# flags in docker/Dockerfile: one worker, several threads).
_login_attempts: Dict[str, Dict[str, object]] = {}
_login_lock = threading.Lock()


def ensure_storage():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_uploads_name_map() -> dict[str, str]:
    global _uploads_name_map_cache
    if _uploads_name_map_cache is not None:
        return _uploads_name_map_cache
    ensure_storage()
    _uploads_name_map_cache = {
        p.name.lower(): p.name
        for p in UPLOADS_DIR.iterdir()
        if p.is_file()
    }
    return _uploads_name_map_cache


def invalidate_uploads_name_map() -> None:
    global _uploads_name_map_cache
    _uploads_name_map_cache = None


def resolve_upload_filename(filename: str) -> str:
    if not filename:
        return ""
    name = Path(filename).name
    if not name:
        return ""
    mapping = get_uploads_name_map()
    return mapping.get(name.lower(), name)


def load_ldap_config() -> dict:
    ensure_storage()
    if not LDAP_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(LDAP_CONFIG_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def configure_session(config: dict) -> None:
    app.secret_key = os.environ.get("SHOME_SECRET_KEY") or config.get("secret_key", "change-me")
    days = int(os.environ.get("SHOME_SESSION_DAYS") or config.get("session_days", 30))
    app.permanent_session_lifetime = timedelta(days=days)


configure_session(load_ldap_config())


def authenticate_ldap(username: str, password: str, config: dict) -> tuple[bool, str]:
    if not config:
        return False, "LDAP configuration not found"

    server_uri = config.get("server_uri")
    if not server_uri:
        return False, "server_uri is missing"

    server = Server(server_uri, use_ssl=bool(config.get("use_ssl", False)))
    user_dn_template = config.get("user_dn_template")
    if user_dn_template:
        user_dn = user_dn_template.format(username=username)
        try:
            conn = Connection(server, user=user_dn, password=password, auto_bind=True)
            conn.unbind()
            return True, ""
        except Exception as exc:
            return False, str(exc)

    bind_dn = config.get("bind_dn")
    bind_password = config.get("bind_password")
    search_base = config.get("search_base")
    search_filter = config.get("search_filter", "(|(sAMAccountName={username})(uid={username}))")
    required_group = config.get("required_group_dn")
    if not all([bind_dn, bind_password, search_base]):
        return False, "Missing LDAP search configuration"

    try:
        service_conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
        service_conn.search(
            search_base,
            search_filter.format(username=username),
            attributes=["distinguishedName", "memberOf"],
        )
        if not service_conn.entries:
            service_conn.unbind()
            return False, "User not found"
        entry = service_conn.entries[0]
        user_dn = entry.entry_dn
        if required_group:
            member_of = entry.memberOf.values if hasattr(entry, "memberOf") else []
            if required_group not in member_of:
                service_conn.unbind()
                return False, "Access denied"
        service_conn.unbind()
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        user_conn.unbind()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def client_key() -> str:
    """Identify the caller for throttling purposes.

    ProxyFix has already rewritten remote_addr from X-Forwarded-For when
    SHOME_TRUST_PROXY is set, so there is nothing to parse here.
    """
    return request.remote_addr or "unknown"


def login_block_seconds(key: str) -> int:
    """Seconds left in the pause, or 0 when the caller may try again."""
    with _login_lock:
        entry = _login_attempts.get(key)
        if not entry:
            return 0
        blocked_until = entry.get("blocked_until")
        if not isinstance(blocked_until, datetime):
            return 0
        remaining = (blocked_until - datetime.utcnow()).total_seconds()
        if remaining <= 0:
            # Pause served: drop the record so the caller gets a fresh batch.
            _login_attempts.pop(key, None)
            return 0
        return int(remaining) + 1


def register_login_failure(key: str) -> int:
    """Count a failed attempt. Returns attempts left before the pause."""
    with _login_lock:
        entry = _login_attempts.setdefault(key, {"failures": 0, "blocked_until": None})
        entry["failures"] = int(entry["failures"]) + 1
        if int(entry["failures"]) >= LOGIN_MAX_ATTEMPTS:
            entry["blocked_until"] = datetime.utcnow() + timedelta(minutes=LOGIN_BLOCK_MINUTES)
            return 0
        return LOGIN_MAX_ATTEMPTS - int(entry["failures"])


def reset_login_failures(key: str) -> None:
    with _login_lock:
        _login_attempts.pop(key, None)


def require_auth(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"success": False, "message": "Authentication required"}), 401
        return handler(*args, **kwargs)

    return wrapper


def load_services():
    ensure_storage()
    if not SERVICES_FILE.exists():
        return None
    try:
        return json.loads(SERVICES_FILE.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []


def save_services(data):
    ensure_storage()
    SERVICES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_uploads_name_map()


def normalize_icon_path(icon: str) -> str:
    if not icon:
        return ""
    icon = icon.strip()
    if not icon:
        return ""
    if icon.startswith("/uploads/"):
        return f"/uploads/{resolve_upload_filename(icon)}"
    if icon.startswith("uploads/"):
        return f"/uploads/{resolve_upload_filename(icon)}"
    if icon.startswith("/assets/images/"):
        return f"/uploads/{resolve_upload_filename(icon)}"
    if icon.startswith("assets/images/"):
        return f"/uploads/{resolve_upload_filename(icon)}"
    if icon.startswith("/assets/"):
        return icon
    if icon.startswith("assets/"):
        return f"/{icon}"
    if icon.startswith("http://") or icon.startswith("https://"):
        return icon
    return f"/uploads/{resolve_upload_filename(icon)}"


def cleanup_unused_uploads(services_data: list[dict]) -> None:
    ensure_storage()
    used_files = set()
    for service in services_data:
        icon = normalize_icon_path(str(service.get("icon", "")))
        if icon.startswith("/uploads/"):
            used_files.add(icon.replace("/uploads/", ""))

    settings = load_settings()
    background_url = str(settings.get("backgroundUrl", "")) if isinstance(settings, dict) else ""
    background_icon = normalize_icon_path(background_url)
    if background_icon.startswith("/uploads/"):
        used_files.add(background_icon.replace("/uploads/", ""))

    for file_path in UPLOADS_DIR.iterdir():
        if file_path.is_file() and file_path.name not in used_files:
            file_path.unlink(missing_ok=True)


def load_settings():
    ensure_storage()
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def save_settings(data):
    ensure_storage()
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_uploads_name_map()


def is_allowed(file_storage) -> bool:
    content_type = (getattr(file_storage, "mimetype", "") or "").lower()
    filename = getattr(file_storage, "filename", "") or ""
    suffix = Path(filename).suffix.lower()

    # A known image extension is enough: some clients send image bytes as
    # application/octet-stream, and rejecting those broke real uploads.
    if suffix:
        return suffix in ALLOWED_UPLOAD_EXTENSIONS
    # No extension: trust the declared type, the real one is derived below.
    return content_type.startswith("image/")


def extension_from_mimetype(content_type: str) -> str:
    ctype = (content_type or "").lower()
    custom_map = {
        "image/jpg": ".jpg",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "image/x-icon": ".ico",
        "image/vnd.microsoft.icon": ".ico",
        "image/tiff": ".tiff",
        "image/avif": ".avif",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    if ctype in custom_map:
        return custom_map[ctype]
    guessed = mimetypes.guess_extension(ctype)
    return guessed or ".img"


def redirect_to_login():
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\" />"
        "<meta http-equiv=\"refresh\" content=\"0; url=/login\" /></head>"
        "<body><a href=\"/login\">Go to sign in</a></body></html>",
        302,
    )


@app.errorhandler(413)
def too_large(_error):
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({"success": False, "message": f"Файл слишком большой (лимит {limit_mb} МБ)"}), 413


@app.route("/css.css")
def stylesheet():
    return send_from_directory(BASE_DIR, "css.css")


@app.route("/")
def index():
    if not session.get("user"):
        return redirect_to_login()
    return send_from_directory(BASE_DIR, "iisstart.htm")


@app.route("/app")
def app_page():
    if not session.get("user"):
        return redirect_to_login()
    return send_from_directory(BASE_DIR, "iisstart.htm")


@app.route("/login")
def login_page():
    if session.get("user"):
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\" />"
            "<meta http-equiv=\"refresh\" content=\"0; url=/app\" /></head>"
            "<body><a href=\"/app\">Go to dashboard</a></body></html>",
            302,
        )
    return send_from_directory(BASE_DIR, "login.htm")


@app.route("/api/auth/status")
def auth_status():
    return jsonify({"authenticated": bool(session.get("user")), "user": session.get("user")})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid payload"}), 400

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    if not username or not password:
        return jsonify({"success": False, "message": "Enter username and password"}), 400

    key = client_key()
    blocked = login_block_seconds(key)
    if blocked:
        minutes, seconds = divmod(blocked, 60)
        wait = f"{minutes} мин {seconds} сек" if minutes else f"{seconds} сек"
        return (
            jsonify({"success": False, "message": f"Слишком много попыток. Повторите через {wait}"}),
            429,
        )

    config = load_ldap_config()
    ok, error = authenticate_ldap(username, password, config)
    if not ok:
        left = register_login_failure(key)
        message = error or "Authentication failed"
        if left == 0:
            message = f"Слишком много попыток. Вход заблокирован на {LOGIN_BLOCK_MINUTES} мин"
        elif left <= 3:
            message = f"{message}. Осталось попыток: {left}"
        return jsonify({"success": False, "message": message}), 401

    reset_login_failures(key)
    session["user"] = username
    session.permanent = True
    return jsonify({"success": True})


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/services", methods=["GET", "POST"])
@require_auth
def services():
    if request.method == "GET":
        items = load_services()
        if items is None:
            return jsonify({"initialized": False, "items": []})
        normalized_items = []
        changed = False
        for service in items:
            if not isinstance(service, dict):
                continue
            normalized_icon = normalize_icon_path(str(service.get("icon", "")))
            if normalized_icon != str(service.get("icon", "")):
                changed = True
            normalized_items.append({**service, "icon": normalized_icon})
        if changed:
            save_services(normalized_items)
            items = normalized_items
        return jsonify({"initialized": True, "items": items})
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"success": False, "message": "Invalid payload"}), 400

    normalized = []
    for service in data:
        if not isinstance(service, dict):
            continue
        normalized.append(
            {
                **service,
                "icon": normalize_icon_path(str(service.get("icon", ""))),
            }
        )

    save_services(normalized)
    cleanup_unused_uploads(normalized)
    return jsonify({"success": True})


@app.route("/api/settings", methods=["GET", "POST"])
@require_auth
def settings():
    if request.method == "GET":
        return jsonify(load_settings())

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid payload"}), 400

    save_settings(data)
    return jsonify({"success": True})


@app.route("/api/upload", methods=["POST"])
@require_auth
def upload():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "File not found"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected"}), 400

    if not is_allowed(file):
        return jsonify({"success": False, "message": "Unsupported file type"}), 400

    ensure_storage()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    safe_name = secure_filename(file.filename)
    if not Path(safe_name).suffix:
        safe_name = f"{safe_name}{extension_from_mimetype(getattr(file, 'mimetype', '') or '')}"

    # secure_filename() and the mimetype fallback can both change the extension,
    # so the name we are about to write is checked, not the one we were given.
    if Path(safe_name).suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({"success": False, "message": "Unsupported file type"}), 400

    target_name = f"{timestamp}_{safe_name}"
    target_path = UPLOADS_DIR / target_name
    file.save(target_path)
    invalidate_uploads_name_map()

    return jsonify({"success": True, "url": f"/uploads/{target_name}"})


@app.route("/uploads/<path:filename>")
@require_auth
def uploaded_file(filename):
    response = send_from_directory(UPLOADS_DIR, filename)
    # Belt and braces for SVG: harmless inside <img>, but opening one directly
    # would otherwise run its script on our origin.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


ensure_storage()

if __name__ == "__main__":
    configure_session(load_ldap_config())
    app.run(
        host=os.environ.get("SHOME_HOST", "0.0.0.0"),
        port=int(os.environ.get("SHOME_PORT", "8080")),
        debug=os.environ.get("SHOME_DEBUG", "0") == "1",
    )