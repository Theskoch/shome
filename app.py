import json
import sys
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "_pydeps"))

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.utils import secure_filename
from ldap3 import Connection, Server

APP_DATA_DIR = BASE_DIR / "App_Data"
UPLOADS_DIR = BASE_DIR / "uploads"
SERVICES_FILE = APP_DATA_DIR / "services.json"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
LDAP_CONFIG_FILE = APP_DATA_DIR / "ldap_config.json"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")


def ensure_storage():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def load_ldap_config() -> dict:
    ensure_storage()
    if not LDAP_CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(LDAP_CONFIG_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def configure_session(config: dict) -> None:
    app.secret_key = config.get("secret_key", "change-me")
    days = int(config.get("session_days", 30))
    app.permanent_session_lifetime = timedelta(days=days)


configure_session(load_ldap_config())


def authenticate_ldap(username: str, password: str, config: dict) -> tuple[bool, str]:
    if not config:
        return False, "LDAP конфигурация не найдена"

    server_uri = config.get("server_uri")
    if not server_uri:
        return False, "server_uri не указан"

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
    if not all([bind_dn, bind_password, search_base]):
        return False, "Недостаточно данных для поиска пользователя"

    try:
        service_conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
        service_conn.search(search_base, search_filter.format(username=username), attributes=["distinguishedName"])
        if not service_conn.entries:
            service_conn.unbind()
            return False, "Пользователь не найден"
        user_dn = service_conn.entries[0].entry_dn
        service_conn.unbind()
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        user_conn.unbind()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def require_auth(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"success": False, "message": "Требуется вход"}), 401
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


def normalize_icon_path(icon: str) -> str:
    if not icon:
        return ""
    if icon.startswith("/uploads/"):
        return icon
    if icon.startswith("/assets/images/"):
        return icon
    if icon.startswith("assets/images/"):
        return f"/{icon}"
    if icon.startswith("http://") or icon.startswith("https://"):
        return icon
    return f"/assets/images/{icon}"


def cleanup_unused_uploads(services_data: list[dict]) -> None:
    ensure_storage()
    used_files = set()
    for service in services_data:
        icon = normalize_icon_path(str(service.get("icon", "")))
        if icon.startswith("/uploads/"):
            used_files.add(icon.replace("/uploads/", ""))

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


def is_allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "iisstart.htm")


@app.route("/api/auth/status")
def auth_status():
    return jsonify({"authenticated": bool(session.get("user")), "user": session.get("user")})


@app.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Неверный формат данных"}), 400

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    if not username or not password:
        return jsonify({"success": False, "message": "Введите логин и пароль"}), 400

    config = load_ldap_config()
    ok, error = authenticate_ldap(username, password, config)
    if not ok:
        return jsonify({"success": False, "message": error or "Ошибка авторизации"}), 401

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
        return jsonify({"initialized": True, "items": items})
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({"success": False, "message": "Неверный формат данных"}), 400

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
        return jsonify({"success": False, "message": "Неверный формат данных"}), 400

    save_settings(data)
    return jsonify({"success": True})


@app.route("/api/upload", methods=["POST"])
@require_auth
def upload():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "Файл не найден"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "Файл не выбран"}), 400

    if not is_allowed(file.filename):
        return jsonify({"success": False, "message": "Недопустимый формат файла"}), 400

    ensure_storage()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    safe_name = secure_filename(file.filename)
    target_name = f"{timestamp}_{safe_name}"
    target_path = UPLOADS_DIR / target_name
    file.save(target_path)

    return jsonify({"success": True, "url": f"/uploads/{target_name}"})


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOADS_DIR, filename)


if __name__ == "__main__":
    ensure_storage()
    configure_session(load_ldap_config())
    app.run(host="0.0.0.0", port=8080, debug=True)