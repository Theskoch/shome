import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "_pydeps"))

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

APP_DATA_DIR = BASE_DIR / "App_Data"
UPLOADS_DIR = BASE_DIR / "uploads"
SERVICES_FILE = APP_DATA_DIR / "services.json"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")


def ensure_storage():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


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


@app.route("/api/services", methods=["GET", "POST"])
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
def settings():
    if request.method == "GET":
        return jsonify(load_settings())

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Неверный формат данных"}), 400

    save_settings(data)
    return jsonify({"success": True})


@app.route("/api/upload", methods=["POST"])
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
    app.run(host="0.0.0.0", port=8080, debug=True)