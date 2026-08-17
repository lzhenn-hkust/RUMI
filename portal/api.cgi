#!/home/lzhenn/array74/soft/anaconda3/bin/python3
import json
import os
import sys
import traceback
import urllib.parse
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "backend"))

from portal_lib import (  # noqa: E402
    ACCEPTED_UPLOAD_STATUSES,
    DATA_DIR,
    INACTIVE_UPLOAD_STATUSES,
    INCOMING_DIR,
    LOG_DIR,
    MAX_CHUNK_BYTES,
    MAX_UPLOAD_BYTES,
    SUBMISSIONS_DIR,
    USER_STORAGE_QUOTA_BYTES,
    PortalError,
    constants_payload,
    connect_db,
    create_session,
    csrf_value,
    destroy_session,
    ensure_registration_code,
    file_kind,
    get_session_user,
    import_whitelist,
    is_whitelisted,
    last_admin_guard,
    load_whitelist_file,
    make_user_public,
    new_token,
    normalize_email,
    parse_rumi_filename,
    require_role,
    safe_file_name,
    sha256_file,
    slugify,
    upload_record_public,
    user_storage_bytes,
    utcnow,
    validate_submission,
    verify_password,
    hash_password,
)


STATUS_TEXT = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    429: "Too Many Requests",
    500: "Internal Server Error",
}


def query_params():
    return urllib.parse.parse_qs(os.environ.get("QUERY_STRING", ""), keep_blank_values=True)


def query_one(name, default=""):
    values = query_params().get(name)
    return values[0] if values else default


def request_cookie(name):
    cookies = os.environ.get("HTTP_COOKIE", "")
    for part in cookies.split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        if key == name:
            return urllib.parse.unquote(value)
    return ""


def cookie_path():
    script = os.environ.get("SCRIPT_NAME", "/")
    base = script.rsplit("/", 1)[0] or "/"
    return base + "/"


def session_cookie(token, expires=None, clear=False):
    attrs = [
        "Path=" + cookie_path(),
        "HttpOnly",
        "Secure",
        "SameSite=Lax",
    ]
    if clear:
        attrs.append("Max-Age=0")
        token = ""
    elif expires:
        attrs.append("Max-Age=" + str(7 * 24 * 3600))
    return "rumi_session=" + urllib.parse.quote(token) + "; " + "; ".join(attrs)


def csrf_cookie(token, clear=False):
    attrs = [
        "Path=" + cookie_path(),
        "Secure",
        "SameSite=Lax",
    ]
    if clear:
        attrs.append("Max-Age=0")
        value = ""
    else:
        attrs.append("Max-Age=" + str(7 * 24 * 3600))
        value = csrf_value(token)
    return "rumi_csrf=" + urllib.parse.quote(value) + "; " + "; ".join(attrs)


def send_json(payload, status=200, cookies=None):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    print(f"Status: {status} {STATUS_TEXT.get(status, 'OK')}")
    print("Content-Type: application/json; charset=utf-8")
    print(f"Content-Length: {len(body)}")
    print("X-Content-Type-Options: nosniff")
    print("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
    print("Cache-Control: no-store")
    for cookie in cookies or []:
        print("Set-Cookie: " + cookie)
    print()
    sys.stdout.flush()
    sys.stdout.buffer.write(body)


def send_file(path, download_name, content_type):
    size = path.stat().st_size
    print("Status: 200 OK")
    print(f"Content-Type: {content_type}")
    print(f"Content-Length: {size}")
    print("X-Content-Type-Options: nosniff")
    print("Cache-Control: no-store")
    print(f"Content-Disposition: attachment; filename=\"{download_name}\"")
    print()
    with open(path, "rb") as handle:
        sys.stdout.flush()
        sys.stdout.buffer.write(handle.read())


def read_body(max_bytes=2 * 1024 * 1024):
    length = int(os.environ.get("CONTENT_LENGTH") or "0")
    if length > max_bytes:
        raise PortalError(400, "Request body is too large.")
    return sys.stdin.buffer.read(length)


def read_json():
    body = read_body()
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise PortalError(400, "Invalid JSON request body.")


def read_raw_body(max_bytes=32 * 1024 * 1024):
    length = int(os.environ.get("CONTENT_LENGTH") or "0")
    if length > max_bytes:
        raise PortalError(400, "Upload chunk is too large.")
    return sys.stdin.buffer.read(length)


def require_portal_header():
    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    if method in ("POST", "PUT", "DELETE") and os.environ.get("HTTP_X_RUMI_PORTAL") != "1":
        raise PortalError(403, "Missing portal request header.")
    session_token = request_cookie("rumi_session")
    action = query_one("action")
    if method in ("POST", "PUT", "DELETE") and session_token and action not in ("login", "register"):
        expected = csrf_value(session_token)
        provided = os.environ.get("HTTP_X_CSRF_TOKEN", "")
        if not provided or not provided == expected:
            raise PortalError(403, "Invalid security token. Refresh the page and try again.")


def current_user(con):
    return get_session_user(con, request_cookie("rumi_session"))


def require_approved_user(con):
    user = current_user(con)
    if not user or user.get("status") != "approved":
        raise PortalError(401, "Please sign in with an approved account.")
    return user


def require_admin(con):
    user = require_approved_user(con)
    require_role(user, "admin")
    return user


def clean_text(value, limit=500):
    value = (value or "").strip()
    return value[:limit]


def client_ip():
    forwarded = os.environ.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:64]
    return os.environ.get("REMOTE_ADDR", "")[:64]


def record_login_attempt(con, email, success):
    con.execute(
        "INSERT INTO login_attempts(email, ip, success, attempted_at) VALUES (?, ?, ?, ?)",
        (normalize_email(email), client_ip(), 1 if success else 0, utcnow()),
    )
    con.execute(
        "DELETE FROM login_attempts WHERE attempted_at < datetime('now', '-1 day')"
    )
    con.commit()


def too_many_login_attempts(con, email):
    row = con.execute(
        """
        SELECT COUNT(*) AS c
        FROM login_attempts
        WHERE email = ?
          AND ip = ?
          AND success = 0
          AND attempted_at >= datetime('now', '-15 minutes')
        """,
        (normalize_email(email), client_ip()),
    ).fetchone()
    return int(row["c"] or 0) >= 10


def remove_upload_files(row):
    for key in ("stored_path", "temp_path"):
        value = row[key]
        if not value:
            continue
        path = Path(value)
        try:
            path.relative_to(DATA_DIR)
        except ValueError:
            continue
        if path.exists() and path.is_file():
            path.unlink()
        for parent in path.parents:
            if parent == DATA_DIR or parent == SUBMISSIONS_DIR or parent == INCOMING_DIR:
                break
            try:
                parent.rmdir()
            except OSError:
                break


def log_exception(exc):
    request_id = uuid.uuid4().hex[:12]
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "api_errors.log", "a", encoding="utf-8") as handle:
            handle.write(f"\n[{utcnow()}] request_id={request_id} action={query_one('action')} type={type(exc).__name__}\n")
            handle.write(traceback.format_exc())
    except Exception:
        pass
    return request_id


def metadata_from_payload(payload):
    fields = [
        "experiment",
        "model",
        "event",
        "member",
        "version",
        "forcing_mode",
        "forcing_source",
        "forcing_data",
        "forcing_data_version",
        "forcing_resolution",
        "forcing_update_interval",
        "simulation_start_time",
        "initialization_time",
        "forecast_initialization_time",
        "forecast_lead_time_hours",
        "horizontal_resolution",
        "vertical_levels",
        "model_top_pressure",
        "microphysics_scheme",
        "cumulus_scheme",
        "pbl_scheme",
        "radiation_scheme",
        "land_surface_scheme",
        "urban_scheme",
        "surface_layer_scheme",
        "turbulence_closure",
        "landuse_dataset",
        "urban_morphology_source",
        "terrain_dataset",
        "soil_dataset",
        "technical_notes",
    ]
    return {field: clean_text(payload.get(field, ""), 3000 if field == "technical_notes" else 500) for field in fields}


def handle_me(con):
    user = current_user(con)
    stats = {}
    if user:
        if user["role"] == "admin":
            stats = {
                "pending_users": con.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE status = 'pending'"
                ).fetchone()["c"],
                "uploads": con.execute("SELECT COUNT(*) AS c FROM uploads").fetchone()["c"],
            }
        else:
            stats = {
                "uploads": con.execute(
                    "SELECT COUNT(*) AS c FROM uploads WHERE user_id = ?", (user["id"],)
                ).fetchone()["c"],
            }
    return {"ok": True, "user": make_user_public(user), "stats": stats, "constants": constants_payload()}


def handle_register(con):
    payload = read_json()
    email = normalize_email(payload.get("email"))
    name = clean_text(payload.get("name"), 120)
    institution = clean_text(payload.get("institution"), 200)
    password = payload.get("password") or ""
    registration_code = clean_text(payload.get("registration_code"), 120)
    if not email or not name or not institution or not password:
        raise PortalError(400, "Email, name, institution, and password are required.")
    if registration_code != ensure_registration_code(con):
        raise PortalError(403, "Invalid registration code.")
    if len(password) < 10:
        raise PortalError(400, "Password must be at least 10 characters.")
    if not is_whitelisted(con, email):
        raise PortalError(403, "This email is not on the RUMI modeler whitelist.")
    if con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise PortalError(409, "An account already exists for this email.")
    salt, digest = hash_password(password)
    now = utcnow()
    con.execute(
        """
        INSERT INTO users(email, name, institution, role, status, password_salt, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, 'modeler', 'approved', ?, ?, ?, ?)
        """,
        (email, name, institution, salt, digest, now, now),
    )
    con.commit()
    row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    token, expires = create_session(con, row["id"])
    con.execute("UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?", (now, now, row["id"]))
    con.commit()
    row = con.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return {
        "payload": {
            "ok": True,
            "message": "Registration complete. You are signed in.",
            "user": make_user_public(row),
            "constants": constants_payload(),
        },
        "cookies": [session_cookie(token, expires=expires), csrf_cookie(token)],
    }


def handle_login(con):
    payload = read_json()
    email = normalize_email(payload.get("email"))
    password = payload.get("password") or ""
    if too_many_login_attempts(con, email):
        raise PortalError(429, "Too many failed attempts. Try again later.")
    row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not verify_password(password, row["password_salt"], row["password_hash"]):
        record_login_attempt(con, email, False)
        raise PortalError(401, "Invalid email or password.")
    if row["status"] != "approved":
        record_login_attempt(con, email, False)
        raise PortalError(403, "This account is not approved yet.")
    record_login_attempt(con, email, True)
    token, expires = create_session(con, row["id"])
    now = utcnow()
    con.execute("UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?", (now, now, row["id"]))
    con.commit()
    row = con.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return {
        "payload": {"ok": True, "user": make_user_public(row), "constants": constants_payload()},
        "cookies": [session_cookie(token, expires=expires), csrf_cookie(token)],
    }


def handle_logout(con):
    read_json()
    destroy_session(con, request_cookie("rumi_session"))
    return {"payload": {"ok": True}, "cookies": [session_cookie("", clear=True), csrf_cookie("", clear=True)]}


def handle_change_password(con):
    user = require_approved_user(con)
    payload = read_json()
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""
    if len(new_password) < 10:
        raise PortalError(400, "New password must be at least 10 characters.")
    row = con.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row or not verify_password(current_password, row["password_salt"], row["password_hash"]):
        raise PortalError(401, "Current password is incorrect.")
    salt, digest = hash_password(new_password)
    now = utcnow()
    con.execute(
        "UPDATE users SET password_salt = ?, password_hash = ?, updated_at = ? WHERE id = ?",
        (salt, digest, now, user["id"]),
    )
    con.commit()
    return {"ok": True}


def handle_admin_users(con):
    require_admin(con)
    users = [
        make_user_public(row)
        for row in con.execute("SELECT * FROM users ORDER BY status, institution, name").fetchall()
    ]
    whitelist = [
        dict(row)
        for row in con.execute("SELECT * FROM whitelist ORDER BY email").fetchall()
    ]
    return {"ok": True, "users": users, "whitelist": whitelist}


def handle_admin_create_user(con):
    require_admin(con)
    payload = read_json()
    email = normalize_email(payload.get("email"))
    name = clean_text(payload.get("name"), 120)
    institution = clean_text(payload.get("institution"), 200)
    role = payload.get("role") if payload.get("role") in ("modeler", "admin") else "modeler"
    status = payload.get("status") if payload.get("status") in ("pending", "approved", "disabled") else "approved"
    password = payload.get("password") or new_token()[:16]
    if not email or not name or not institution:
        raise PortalError(400, "Email, name, and institution are required.")
    if con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise PortalError(409, "A user already exists for this email.")
    now = utcnow()
    con.execute(
        """
        INSERT INTO whitelist(email, source, created_at)
        VALUES (?, 'admin', ?)
        ON CONFLICT(email) DO NOTHING
        """,
        (email, now),
    )
    salt, digest = hash_password(password)
    con.execute(
        """
        INSERT INTO users(email, name, institution, role, status, password_salt, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (email, name, institution, role, status, salt, digest, now, now),
    )
    con.commit()
    return {"ok": True, "temporary_password": password}


def handle_admin_update_user(con):
    admin = require_admin(con)
    payload = read_json()
    user_id = int(payload.get("id") or "0")
    row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise PortalError(404, "User not found.")
    role = payload.get("role") if payload.get("role") in ("modeler", "admin") else row["role"]
    status = payload.get("status") if payload.get("status") in ("pending", "approved", "disabled", "deleted") else row["status"]
    last_admin_guard(con, user_id, role, status)
    name = clean_text(payload.get("name", row["name"]), 120)
    institution = clean_text(payload.get("institution", row["institution"]), 200)
    now = utcnow()
    con.execute(
        "UPDATE users SET name = ?, institution = ?, role = ?, status = ?, updated_at = ? WHERE id = ?",
        (name, institution, role, status, now, user_id),
    )
    if user_id != admin["id"] and status != "approved":
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    con.commit()
    return {"ok": True}


def handle_admin_delete_user(con):
    require_admin(con)
    payload = read_json()
    user_id = int(payload.get("id") or "0")
    last_admin_guard(con, user_id, new_status="deleted")
    now = utcnow()
    con.execute("UPDATE users SET status = 'deleted', updated_at = ? WHERE id = ?", (now, user_id))
    con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    con.commit()
    return {"ok": True}


def handle_admin_whitelist_add(con):
    require_admin(con)
    payload = read_json()
    emails = payload.get("emails") or []
    if isinstance(emails, str):
        emails = [part.strip() for part in emails.replace(",", "\n").splitlines()]
    import_whitelist(con, emails, source="admin")
    return {"ok": True}


def handle_admin_whitelist_delete(con):
    require_admin(con)
    payload = read_json()
    email = normalize_email(payload.get("email"))
    if not email:
        raise PortalError(400, "Email is required.")
    con.execute("DELETE FROM whitelist WHERE email = ?", (email,))
    con.commit()
    return {"ok": True}


def handle_upload_start(con):
    user = require_approved_user(con)
    payload = read_json()
    file_name = safe_file_name(payload.get("file_name"))
    size = int(payload.get("file_size") or 0)
    if size <= 0:
        raise PortalError(400, "File size must be greater than zero.")
    if size > MAX_UPLOAD_BYTES:
        raise PortalError(400, "File exceeds the per-upload size limit.")
    if user_storage_bytes(con, user["id"]) + size > USER_STORAGE_QUOTA_BYTES:
        raise PortalError(400, "User storage quota would be exceeded.")
    kind = file_kind(file_name)
    metadata = metadata_from_payload(payload)
    requested_replacement = clean_text(payload.get("replace_upload_id"), 80)
    if metadata["event"] not in constants_payload()["events"]:
        raise PortalError(400, "Select a valid RUMI event.")
    if not metadata["experiment"] or not metadata["model"]:
        raise PortalError(400, "Experiment and model are required.")
    parsed = parse_rumi_filename(file_name) if kind == "netcdf" else None
    if kind == "netcdf" and not parsed:
        raise PortalError(
            400,
            "File name must follow <RUMI experiment>-<Model>-<Event>-"
            "<YYYYMMDDHHMMSS>[_member][_vNN].nc.",
        )
    if parsed:
        comparisons = (
            ("experiment", str.upper),
            ("model", str.lower),
            ("event", str.upper),
        )
        for field, normalize in comparisons:
            submitted = metadata.get(field, "")
            if submitted and normalize(parsed[field]) != normalize(submitted):
                raise PortalError(
                    400,
                    f"File name {field} does not match the submitted metadata.",
                )
    timestamp_utc = parsed["timestamp"] if parsed else None
    inactive_placeholders = ", ".join("?" for _ in INACTIVE_UPLOAD_STATUSES)
    existing = con.execute(
        f"""
        SELECT * FROM uploads
        WHERE user_id = ? AND file_name = ?
          AND status NOT IN ({inactive_placeholders})
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user["id"], file_name, *INACTIVE_UPLOAD_STATUSES),
    ).fetchone()
    if existing and requested_replacement != existing["upload_id"]:
        raise PortalError(
            409,
            "A submission with this file name already exists.",
            {
                "code": "duplicate_filename",
                "existing": upload_record_public(existing),
            },
        )
    if requested_replacement and not existing:
        raise PortalError(
            409,
            "The submission selected for replacement is no longer active. Refresh and try again.",
            {"code": "replacement_stale"},
        )
    upload_id = new_token()[:22]
    temp_path = INCOMING_DIR / (upload_id + ".part")
    now = utcnow()
    con.execute(
        """
        INSERT INTO uploads(
            upload_id, user_id, institution, file_name, file_size, received_bytes, file_kind,
            status, experiment, model, event, timestamp_utc, member, version,
            metadata_json, temp_path, replaces_upload_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 0, ?, 'receiving', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            upload_id,
            user["id"],
            user["institution"],
            file_name,
            size,
            kind,
            metadata["experiment"],
            metadata["model"],
            metadata["event"],
            timestamp_utc,
            metadata["member"],
            metadata["version"],
            json.dumps(metadata, ensure_ascii=True),
            str(temp_path),
            existing["upload_id"] if existing else None,
            now,
            now,
        ),
    )
    con.commit()
    return {"ok": True, "upload_id": upload_id, "chunk_size": constants_payload()["chunk_size"]}


def handle_upload_chunk(con):
    user = require_approved_user(con)
    upload_id = query_one("upload_id")
    offset = int(query_one("offset", "0"))
    row = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    if not row or row["user_id"] != user["id"]:
        raise PortalError(404, "Upload not found.")
    if row["status"] != "receiving":
        raise PortalError(409, "Upload is not accepting chunks.")
    expected = int(row["received_bytes"])
    if offset != expected:
        raise PortalError(409, "Chunk offset does not match server state.", {"expected": expected})
    chunk_len = int(os.environ.get("CONTENT_LENGTH") or "0")
    if chunk_len > MAX_CHUNK_BYTES:
        raise PortalError(400, "Upload chunk is too large.")
    if expected + chunk_len > int(row["file_size"]):
        raise PortalError(400, "Upload exceeds declared file size.")
    chunk = read_raw_body(MAX_CHUNK_BYTES)
    temp_path = Path(row["temp_path"])
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(temp_path, "ab") as handle:
        handle.write(chunk)
    received = expected + len(chunk)
    now = utcnow()
    con.execute(
        "UPDATE uploads SET received_bytes = ?, updated_at = ? WHERE upload_id = ?",
        (received, now, upload_id),
    )
    con.commit()
    return {"ok": True, "received_bytes": received, "file_size": row["file_size"]}


def handle_upload_finish(con):
    user = require_approved_user(con)
    payload = read_json()
    upload_id = payload.get("upload_id") or ""
    row = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    if not row or row["user_id"] != user["id"]:
        raise PortalError(404, "Upload not found.")
    terminal_statuses = set(INACTIVE_UPLOAD_STATUSES) | set(ACCEPTED_UPLOAD_STATUSES)
    inactive_placeholders = ", ".join("?" for _ in INACTIVE_UPLOAD_STATUSES)
    if row["status"] in terminal_statuses:
        return {"ok": True, "upload": upload_record_public(row)}
    if row["status"] not in ("receiving", "validating"):
        raise PortalError(409, "Upload is not ready for validation.")
    if int(row["received_bytes"]) != int(row["file_size"]):
        raise PortalError(409, "Upload is incomplete.")
    if not row["temp_path"]:
        raise PortalError(409, "Temporary upload file is no longer available.")
    temp_path = Path(row["temp_path"])
    if not temp_path.exists():
        raise PortalError(404, "Temporary upload file is missing.")
    metadata = json.loads(row["metadata_json"])
    now = utcnow()
    con.execute(
        "UPDATE uploads SET status = 'validating', updated_at = ? WHERE upload_id = ?",
        (now, upload_id),
    )
    con.commit()
    try:
        digest = sha256_file(temp_path)
        validation = validate_submission(temp_path, row["file_name"], metadata)
    except Exception as exc:
        request_id = log_exception(exc)
        validation = {
            "errors": [
                "The server could not validate this file. "
                f"No submission was accepted. Reference: {request_id}"
            ],
            "warnings": [],
            "summary": {},
        }
        now = utcnow()
        con.execute(
            """
            UPDATE uploads
            SET status = 'server_error', validation_json = ?, updated_at = ?
            WHERE upload_id = ?
            """,
            (json.dumps(validation, ensure_ascii=True), now, upload_id),
        )
        con.commit()
        record = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
        return {"ok": True, "upload": upload_record_public(record)}

    if validation.get("errors"):
        now = utcnow()
        con.execute(
            """
            UPDATE uploads
            SET status = 'rejected', sha256 = ?, validation_json = ?, updated_at = ?
            WHERE upload_id = ?
            """,
            (
                digest,
                json.dumps(validation, ensure_ascii=True),
                now,
                upload_id,
            ),
        )
        con.commit()
        record = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
        return {"ok": True, "upload": upload_record_public(record)}

    accepted_placeholders = ", ".join("?" for _ in ACCEPTED_UPLOAD_STATUSES)
    duplicate = con.execute(
        f"""
        SELECT * FROM uploads
        WHERE user_id = ? AND sha256 = ? AND id != ?
          AND upload_id != COALESCE(?, '')
          AND status IN ({accepted_placeholders})
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            user["id"],
            digest,
            row["id"],
            row["replaces_upload_id"],
            *ACCEPTED_UPLOAD_STATUSES,
        ),
    ).fetchone()
    if duplicate:
        validation["errors"] = [
            f"Identical file content was already accepted as {duplicate['file_name']}."
        ]
        validation.setdefault("summary", {})["duplicate_upload_id"] = duplicate["upload_id"]
        remove_upload_files(row)
        now = utcnow()
        con.execute(
            """
            UPDATE uploads
            SET status = 'duplicate', temp_path = NULL, sha256 = ?,
                validation_json = ?, updated_at = ?
            WHERE upload_id = ?
            """,
            (
                digest,
                json.dumps(validation, ensure_ascii=True),
                now,
                upload_id,
            ),
        )
        con.commit()
        record = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
        return {"ok": True, "upload": upload_record_public(record)}

    final_dir = (
        SUBMISSIONS_DIR
        / slugify(user["institution"])
        / slugify(row["experiment"])
        / slugify(row["model"])
        / row["event"]
    )
    final_path = final_dir / (row["upload_id"] + "_" + safe_file_name(row["file_name"]))
    status = "validated"
    try:
        final_dir.mkdir(parents=True, exist_ok=True)
        temp_path.replace(final_path)
        now = utcnow()
        con.execute(
            """
            UPDATE uploads
            SET status = ?, stored_path = ?, temp_path = NULL, sha256 = ?,
                validation_json = ?, updated_at = ?
            WHERE upload_id = ?
            """,
            (
                status,
                str(final_path),
                digest,
                json.dumps(validation, ensure_ascii=True),
                now,
                upload_id,
            ),
        )
        if row["replaces_upload_id"]:
            con.execute(
                f"""
                UPDATE uploads
                SET status = 'superseded', updated_at = ?
                WHERE upload_id = ? AND user_id = ?
                  AND status NOT IN ({inactive_placeholders})
                """,
                (
                    now,
                    row["replaces_upload_id"],
                    user["id"],
                    *INACTIVE_UPLOAD_STATUSES,
                ),
            )
        con.commit()
    except Exception as exc:
        request_id = log_exception(exc)
        validation["errors"] = [
            "The file passed validation, but the server could not finalize it. "
            f"No submission was accepted. Reference: {request_id}"
        ]
        now = utcnow()
        con.execute(
            """
            UPDATE uploads
            SET status = 'server_error', sha256 = ?, validation_json = ?, updated_at = ?
            WHERE upload_id = ?
            """,
            (
                digest,
                json.dumps(validation, ensure_ascii=True),
                now,
                upload_id,
            ),
        )
        con.commit()
    record = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    return {"ok": True, "upload": upload_record_public(record)}


def handle_uploads(con):
    user = require_approved_user(con)
    if user["role"] == "admin":
        rows = con.execute(
            """
            SELECT uploads.*,
                   users.name AS uploader_name,
                   users.email AS uploader_email,
                   users.institution AS uploader_institution
            FROM uploads
            JOIN users ON users.id = uploads.user_id
            ORDER BY uploads.created_at DESC
            LIMIT 300
            """
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM uploads WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
            (user["id"],),
        ).fetchall()
    return {"ok": True, "uploads": [upload_record_public(row) for row in rows]}


def handle_upload_delete(con):
    user = require_approved_user(con)
    payload = read_json()
    upload_id = payload.get("upload_id") or ""
    row = con.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    if not row:
        raise PortalError(404, "Upload not found.")
    if user["role"] != "admin" and row["user_id"] != user["id"]:
        raise PortalError(403, "You cannot delete this upload.")
    remove_upload_files(row)
    now = utcnow()
    con.execute(
        "UPDATE uploads SET status = 'deleted', stored_path = NULL, temp_path = NULL, updated_at = ? WHERE upload_id = ?",
        (now, upload_id),
    )
    con.commit()
    return {"ok": True}


def handle_bootstrap_info(con):
    require_admin(con)
    admins = con.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND status = 'approved'"
    ).fetchone()["c"]
    whitelist = con.execute("SELECT COUNT(*) AS c FROM whitelist").fetchone()["c"]
    return {"ok": True, "admins": admins, "whitelist": whitelist}


def handle_download(con):
    allowed = {
        "RUMI_template_2d.nc": ("downloads/RUMI_template_2d.nc", "application/octet-stream"),
        "create_ncdf.py": ("downloads/create_ncdf.py", "text/x-python"),
    }
    name = query_one("file")
    if name not in allowed:
        raise PortalError(404, "Download not found.")
    rel_path, content_type = allowed[name]
    path = BASE_DIR / rel_path
    if not path.exists():
        raise PortalError(404, "Download file is missing.")
    send_file(path, name, content_type)
    raise SystemExit(0)


ROUTES = {
    "me": handle_me,
    "register": handle_register,
    "login": handle_login,
    "logout": handle_logout,
    "change_password": handle_change_password,
    "admin_users": handle_admin_users,
    "admin_create_user": handle_admin_create_user,
    "admin_update_user": handle_admin_update_user,
    "admin_delete_user": handle_admin_delete_user,
    "admin_whitelist_add": handle_admin_whitelist_add,
    "admin_whitelist_delete": handle_admin_whitelist_delete,
    "upload_start": handle_upload_start,
    "upload_chunk": handle_upload_chunk,
    "upload_finish": handle_upload_finish,
    "uploads": handle_uploads,
    "upload_delete": handle_upload_delete,
    "bootstrap_info": handle_bootstrap_info,
    "download": handle_download,
}


def main():
    try:
        require_portal_header()
        action = query_one("action", "me")
        handler = ROUTES.get(action)
        if not handler:
            raise PortalError(404, "Unknown API action.")
        with connect_db() as con:
            result = handler(con)
        if isinstance(result, dict) and "payload" in result:
            send_json(result["payload"], cookies=result.get("cookies"))
        else:
            send_json(result)
    except PortalError as exc:
        send_json({"ok": False, "error": exc.message, "details": exc.details}, status=exc.status)
    except Exception as exc:
        request_id = log_exception(exc)
        send_json(
            {
                "ok": False,
                "error": f"Unexpected server error. Reference: {request_id}",
                "details": {},
            },
            status=500,
        )


if __name__ == "__main__":
    main()
