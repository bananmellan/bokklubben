import hmac
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from flask import abort, current_app, jsonify, redirect, request, session, url_for

from .db import execute, one


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def resolve_secret_key(app):
    key = app.config.get("SECRET_KEY")
    if key:
        return key
    path = app.config["DATA_DIR"] / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    path.chmod(0o600)
    return key


def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]


def register(app):
    app.secret_key = resolve_secret_key(app)

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.path == "/healthz":
                return None
            sent = request.form.get("csrf_token", "")
            if not sent or not hmac.compare_digest(sent, session.get("_csrf_token", "")):
                abort(400, "Ogiltig eller saknad CSRF-token")
        return None

    @app.after_request
    def autosave_returns_json(response):
        if request.headers.get("X-Autosave") and response.status_code in (301, 302, 303):
            flashes = session.pop("_flashes", [])
            errors = [m for category, m in flashes if category == "error"]
            if errors:
                return jsonify({"ok": False, "errors": errors})
            return jsonify({"ok": True, "redirect": response.headers.get("Location", "")})
        return response


def current_member():
    mid = session.get("member_id")
    if not mid:
        return None
    return one("SELECT * FROM members WHERE id = ?", (mid,))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_member() is None:
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        member = current_member()
        if member is None:
            return redirect(url_for("main.login"))
        if not member["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def create_login_code(email):
    member = one("SELECT * FROM members WHERE lower(email) = lower(?)", (email.strip(),))
    if member is None:
        return None, None
    execute(
        "UPDATE login_codes SET used_at = ? WHERE member_id = ? AND used_at IS NULL",
        (now_iso(), member["id"]),
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    execute(
        "INSERT INTO login_codes(member_id, code, expires_at) VALUES (?, ?, ?)",
        (member["id"], code, expires),
    )
    return member, code


def send_code_email(member, code, club_name):
    msg = EmailMessage()
    msg["Subject"] = f"Din inloggningskod till {club_name}"
    msg["From"] = current_app.config["SMTP_FROM"]
    msg["To"] = member["email"]
    msg.set_content(
        f"Hej {member['name']}!\n\n"
        f"Din inloggningskod är: {code}\n\n"
        f"Koden gäller i 10 minuter.\n\n"
        f"{club_name}"
    )
    cfg = current_app.config
    with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=cfg["SMTP_TIMEOUT"]) as smtp:
        if cfg["SMTP_STARTTLS"]:
            smtp.starttls()
        if cfg["SMTP_USERNAME"]:
            smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"] or "")
        smtp.send_message(msg)


def verify_code(email, code):
    member = one("SELECT * FROM members WHERE lower(email) = lower(?)", (email.strip(),))
    if member is None:
        return None
    row = one(
        "SELECT * FROM login_codes WHERE member_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
        (member["id"],),
    )
    if row is None or row["attempts"] >= 5 or row["code"] != code.strip():
        if row is not None:
            execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    execute("UPDATE login_codes SET used_at = ? WHERE id = ?", (now_iso(), row["id"]))
    session["member_id"] = member["id"]
    session.permanent = True
    return member
