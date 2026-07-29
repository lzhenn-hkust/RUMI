import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import zipfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = BASE_DIR / "backend"


def configured_data_dir():
    env_dir = os.environ.get("RUMI_PORTAL_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    config = BACKEND_DIR / "data_dir.txt"
    if config.exists():
        value = config.read_text(encoding="utf-8").strip()
        if value:
            return Path(value).expanduser()
    return BASE_DIR / "data"


DATA_DIR = configured_data_dir()
DB_PATH = DATA_DIR / "rumi_portal.sqlite3"
INCOMING_DIR = DATA_DIR / "incoming"
SUBMISSIONS_DIR = DATA_DIR / "submissions"
LOG_DIR = DATA_DIR / "logs"

SESSION_COOKIE = "rumi_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 240000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024
USER_STORAGE_QUOTA_BYTES = 100 * 1024 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
REGISTRATION_CODE_KEY = "registration_code"

INACTIVE_UPLOAD_STATUSES = (
    "deleted",
    "duplicate",
    "failed",
    "rejected",
    "server_error",
    "superseded",
)

ACCEPTED_UPLOAD_STATUSES = (
    "validated",
    "received_manual_review",
)

EVENTS = {
    "MANGKHUT2018": {
        "name": "Typhoon Mangkhut (2018)",
        "start": "2018-09-15T00:00:00Z",
        "end": "2018-09-17T00:00:00Z",
        "category": "Tropical cyclone",
    },
    "HRAIN2023": {
        "name": "Black Rainstorm (2023)",
        "start": "2023-09-06T00:00:00Z",
        "end": "2023-09-09T00:00:00Z",
        "category": "Heavy rain",
    },
    "HRAIN2025": {
        "name": "Black Rainstorm (2025)",
        "start": "2025-08-03T00:00:00Z",
        "end": "2025-08-06T00:00:00Z",
        "category": "Heavy rain",
    },
    "HEAT2022": {
        "name": "Heatwave (2022)",
        "start": "2022-07-22T00:00:00Z",
        "end": "2022-07-25T00:00:00Z",
        "category": "Extreme heat",
    },
    "HEAT2024": {
        "name": "Heatwave (2024)",
        "start": "2024-08-27T00:00:00Z",
        "end": "2024-08-29T00:00:00Z",
        "category": "Extreme heat",
    },
}

EXPERIMENTS = ["ERA5", "FNL", "GFS", "OTHER", "UKMO", "JRA55", "IFS"]

CORE_2D_VARS = [
    "T2M",
    "U10M",
    "V10M",
    "PRATE",
    "SLP",
    "RH2M",
    "TOTAL_PRECIP",
    "PSFC",
    "Q2M",
]

RECOMMENDED_2D_VARS = [
    "TSK",
    "TD2M",
    "LH",
    "HFX",
    "SWDOWN",
    "SWUP",
    "LWDOWN",
    "LWUP",
    "GRDFLX",
    "WSPD10M",
    "WDIR10M",
    "CLDFRAC",
    "CTH",
    "CBH",
    "CWP",
    "IWP",
    "RWP",
    "PW",
    "HOURLY_PRECIP",
    "PRATE_CONV",
    "PRATE_GRID",
    "REFL_COMP",
    "REFL_2KM",
    "CAPE",
    "CIN",
    "PBLH",
    "W850",
    "W500",
    "HELICITY",
    "UH_MAX",
    "WSPD10MAX",
    "SLP_MIN",
    "VORT850",
    "VORT700",
    "PRATE_MAX",
    "FLASH_RATE",
    "IVT",
]

THREE_D_VARS = ["T", "Z", "RH", "U", "V", "OMEGA"]

REQUIRED_GLOBAL_ATTRS = [
    "Conventions",
    "title",
    "institution",
    "source",
    "history",
    "experiment",
    "event",
    "event_name",
    "simulation_start_time",
    "initialization_time",
    "forcing_data",
    "horizontal_resolution",
    "contact",
    "creator_name",
    "creation_date",
    "version",
]

PHYSICS_ATTRS = [
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
]

SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,240}$")
RUMI_FILENAME_RE = re.compile(
    r"^RUMI-([A-Za-z0-9]+)-(.+)-("
    + "|".join(EVENTS.keys())
    + r")-(\d{14})(?:_([A-Za-z0-9._-]+))?(?:_v([0-9]{2,}))?\.nc$"
)


class PortalError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def slugify(value):
    value = (value or "unknown").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    return value[:80] or "unknown"


def normalize_email(email):
    return (email or "").strip().lower()


def ensure_dirs():
    old_umask = os.umask(0o077)
    try:
        for directory in (DATA_DIR, INCOMING_DIR, SUBMISSIONS_DIR, LOG_DIR):
            directory.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(old_umask)
    data_htaccess = DATA_DIR / ".htaccess"
    if not data_htaccess.exists():
        data_htaccess.write_text("Order allow,deny\nDeny from all\n", encoding="utf-8")


def connect_db():
    ensure_dirs()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 5000")
    con.execute("PRAGMA foreign_keys = ON")
    init_schema(con)
    return con


def init_schema(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS whitelist (
            email TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT 'Email List.docx',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            institution TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'modeler',
            status TEXT NOT NULL DEFAULT 'pending',
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            received_bytes INTEGER NOT NULL DEFAULT 0,
            file_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            experiment TEXT NOT NULL,
            model TEXT NOT NULL,
            event TEXT NOT NULL,
            timestamp_utc TEXT,
            member TEXT,
            version TEXT,
            metadata_json TEXT NOT NULL,
            temp_path TEXT,
            stored_path TEXT,
            sha256 TEXT,
            validation_json TEXT,
            replaces_upload_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_uploads_user_id ON uploads(user_id);
        CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status);
        CREATE INDEX IF NOT EXISTS idx_uploads_event ON uploads(event);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            ip TEXT NOT NULL,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_login_attempts_email_ip_time
            ON login_attempts(email, ip, attempted_at);
        """
    )
    upload_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(uploads)").fetchall()
    }
    if "replaces_upload_id" not in upload_columns:
        con.execute("ALTER TABLE uploads ADD COLUMN replaces_upload_id TEXT")
    con.commit()


def hash_password(password, salt_hex=None):
    if salt_hex is None:
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
    else:
        salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt_hex, digest.hex()


def verify_password(password, salt_hex, expected_hex):
    _, candidate = hash_password(password, salt_hex)
    return secrets.compare_digest(candidate, expected_hex)


def new_token():
    return secrets.token_urlsafe(32)


def csrf_value(session_token):
    return hmac.new(
        session_token.encode("utf-8"),
        b"rumi-csrf-v1",
        hashlib.sha256,
    ).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(con, user_id):
    token = new_token()
    now = utcnow()
    expires = (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SESSION_DAYS)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    con.execute(
        """
        INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen)
        VALUES (?, ?, ?, ?, ?)
        """,
        (token_hash(token), user_id, now, expires, now),
    )
    con.commit()
    return token, expires


def get_session_user(con, token):
    if not token:
        return None
    now = utcnow()
    row = con.execute(
        """
        SELECT u.*
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at > ?
        """,
        (token_hash(token), now),
    ).fetchone()
    if not row:
        return None
    con.execute(
        "UPDATE sessions SET last_seen = ? WHERE token_hash = ?",
        (now, token_hash(token)),
    )
    con.commit()
    return dict(row)


def destroy_session(con, token):
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        con.commit()


def is_whitelisted(con, email):
    return (
        con.execute("SELECT 1 FROM whitelist WHERE email = ?", (normalize_email(email),)).fetchone()
        is not None
    )


def load_whitelist_file(path=None):
    path = Path(path or (BACKEND_DIR / "whitelist_emails.txt"))
    if not path.exists():
        return []
    emails = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            emails.append(line)
    return sorted(set(emails))


def import_whitelist(con, emails, source="Email List.docx"):
    now = utcnow()
    for email in emails:
        email = normalize_email(email)
        if email:
            con.execute(
                """
                INSERT INTO whitelist(email, source, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(email) DO NOTHING
                """,
                (email, source, now),
            )
    con.commit()


def get_setting(con, key):
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def set_setting(con, key, value):
    con.execute(
        """
        INSERT INTO settings(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, utcnow()),
    )
    con.commit()


def ensure_registration_code(con):
    code = get_setting(con, REGISTRATION_CODE_KEY)
    if not code:
        code = "RUMI-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "")[:12]
        set_setting(con, REGISTRATION_CODE_KEY, code)
    return code


def make_user_public(row):
    if not row:
        return None
    if isinstance(row, sqlite3.Row):
        row = dict(row)
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "institution": row["institution"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login": row["last_login"],
    }


def require_role(user, role):
    if not user or user.get("status") != "approved":
        raise PortalError(401, "Please sign in with an approved account.")
    if role == "admin" and user.get("role") != "admin":
        raise PortalError(403, "Administrator access is required.")


def last_admin_guard(con, target_user_id, new_role=None, new_status=None):
    target = con.execute("SELECT * FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target or target["role"] != "admin" or target["status"] != "approved":
        return
    next_role = new_role if new_role is not None else target["role"]
    next_status = new_status if new_status is not None else target["status"]
    if next_role == "admin" and next_status == "approved":
        return
    admins = con.execute(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND status = 'approved'"
    ).fetchone()["c"]
    if admins <= 1:
        raise PortalError(400, "At least one approved administrator must remain.")


def user_storage_bytes(con, user_id):
    excluded = ", ".join("?" for _ in INACTIVE_UPLOAD_STATUSES)
    row = con.execute(
        f"""
        SELECT COALESCE(SUM(file_size), 0) AS total
        FROM uploads
        WHERE user_id = ? AND status NOT IN ({excluded})
        """,
        (user_id, *INACTIVE_UPLOAD_STATUSES),
    ).fetchone()
    return int(row["total"] or 0)


def safe_file_name(name):
    name = os.path.basename((name or "").strip())
    if not name or name.startswith(".") or not SAFE_FILENAME_RE.match(name):
        raise PortalError(400, "File name contains unsupported characters.")
    return name


def file_kind(name):
    lower = name.lower()
    if lower.endswith(".nc"):
        return "netcdf"
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        return "tar"
    raise PortalError(400, "Upload a .nc, .zip, .tar.gz, or .tgz file.")


def parse_rumi_filename(name):
    match = RUMI_FILENAME_RE.match(name)
    if not match:
        return None
    experiment, model, event, stamp, member, version = match.groups()
    try:
        ts = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return {
        "experiment": experiment,
        "model": model,
        "event": event,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "member": member or "",
        "version": version or "",
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(args, timeout=60):
    env = os.environ.copy()
    env["PATH"] = "/home/lzhenn/array74/soft/anaconda3/bin:/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def ncdump_executable():
    candidates = [
        os.environ.get("RUMI_NCDUMP"),
        "/usr/bin/ncdump",
        "/usr/local/bin/ncdump",
        shutil.which("ncdump"),
        "/home/lzhenn/array74/soft/anaconda3/bin/ncdump",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise PortalError(500, "NetCDF validation tool is unavailable.")


def netcdf_kind(path):
    ncdump = ncdump_executable()
    proc = run_command([ncdump, "-k", str(path)], timeout=30)
    if proc.returncode != 0:
        raise PortalError(400, "ncdump could not read the file.", {"stderr": proc.stderr.strip()})
    return proc.stdout.strip()


def netcdf_header(path):
    ncdump = ncdump_executable()
    proc = run_command([ncdump, "-h", str(path)], timeout=90)
    if proc.returncode != 0:
        raise PortalError(400, "ncdump header extraction failed.", {"stderr": proc.stderr.strip()})
    return proc.stdout


def header_has_var(header, name):
    return re.search(r"\b(?:byte|char|short|int|int64|float|double)\s+" + re.escape(name) + r"\s*\(", header) is not None


def header_dim(header, name):
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*(\d+)\s*;", header)
    return int(match.group(1)) if match else None


def header_attr(header, name):
    match = re.search(r":\s*" + re.escape(name) + r"\s*=\s*\"([^\"]*)\"", header)
    return match.group(1) if match else None


def validate_timestamp_in_event(timestamp_iso, event):
    ts = parse_utc(timestamp_iso)
    if not ts or event not in EVENTS:
        return None
    start = parse_utc(EVENTS[event]["start"])
    end = parse_utc(EVENTS[event]["end"])
    return start <= ts <= end


def validate_netcdf(path, filename, metadata):
    errors = []
    warnings = []
    summary = {}

    parsed = parse_rumi_filename(filename)
    if not parsed:
        errors.append("File name must follow RUMI-<Experiment>-<Model>-<Event>-<YYYYMMDDHHMMSS>[_member][_vNN].nc.")
    else:
        summary["filename"] = parsed
        if metadata.get("experiment") and parsed["experiment"].upper() != metadata.get("experiment", "").upper():
            warnings.append("File name experiment does not match the submitted metadata.")
        if metadata.get("model") and parsed["model"].lower() != metadata.get("model", "").lower():
            warnings.append("File name model does not match the submitted metadata.")
        if metadata.get("event") and parsed["event"] != metadata.get("event"):
            warnings.append("File name event does not match the submitted metadata.")
        if validate_timestamp_in_event(parsed["timestamp"], parsed["event"]) is False:
            warnings.append("File timestamp is outside the baseline simulation period for the selected event.")

    try:
        kind = netcdf_kind(path)
        summary["netcdf_kind"] = kind
        if "netCDF-4" not in kind:
            errors.append("File is readable by ncdump but is not NetCDF4.")
        header = netcdf_header(path)
    except PortalError as exc:
        if exc.status >= 500:
            raise
        errors.append(exc.message)
        if exc.details.get("stderr"):
            warnings.append(exc.details["stderr"][:600])
        return {"errors": errors, "warnings": warnings, "summary": summary}

    missing_core = [name for name in CORE_2D_VARS if not header_has_var(header, name)]
    if missing_core:
        errors.append("Missing core 2D variables: " + ", ".join(missing_core))

    present_recommended = [name for name in RECOMMENDED_2D_VARS if header_has_var(header, name)]
    present_3d = [name for name in THREE_D_VARS if header_has_var(header, name)]
    summary["recommended_2d_count"] = len(present_recommended)
    summary["three_d_present"] = present_3d

    lat = header_dim(header, "lat")
    lon = header_dim(header, "lon")
    south_north = header_dim(header, "south_north")
    west_east = header_dim(header, "west_east")
    summary["dimensions"] = {
        "lat": lat,
        "lon": lon,
        "south_north": south_north,
        "west_east": west_east,
    }
    has_standard_latlon = lat == 111 and lon == 152
    has_standard_alias = south_north == 111 and west_east == 152
    if not (has_standard_latlon or has_standard_alias):
        errors.append("Standard grid dimensions should be 111 lat by 152 lon.")
    if has_standard_alias and not has_standard_latlon:
        warnings.append("File uses south_north/west_east dimensions; standard 2D submissions should prefer lat/lon.")

    missing_attrs = [name for name in REQUIRED_GLOBAL_ATTRS if header_attr(header, name) is None]
    if missing_attrs:
        warnings.append("Missing required global attributes: " + ", ".join(missing_attrs))

    missing_physics = [name for name in PHYSICS_ATTRS if header_attr(header, name) is None]
    if missing_physics:
        warnings.append("Missing physics/surface documentation attributes: " + ", ".join(missing_physics))

    conventions = header_attr(header, "Conventions")
    if conventions and "CF-1.8" not in conventions:
        warnings.append("Conventions attribute does not include CF-1.8.")

    attr_event = header_attr(header, "event")
    if parsed and attr_event and attr_event != parsed["event"]:
        warnings.append("Global attribute event does not match file name.")

    attr_experiment = header_attr(header, "experiment")
    if parsed and attr_experiment:
        normalized = attr_experiment.replace("RUMI-", "").upper()
        if normalized != parsed["experiment"].upper():
            warnings.append("Global attribute experiment does not match file name.")

    return {"errors": errors, "warnings": warnings, "summary": summary}


def validate_archive(path, filename, metadata):
    errors = []
    warnings = []
    summary = {"archive_members": 0, "netcdf_files": 0, "documentation_files": 0}
    lower = filename.lower()
    docs_ext = (".pdf", ".docx", ".txt", ".md")

    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                names = [info.filename for info in archive.infolist() if not info.is_dir()]
        else:
            with tarfile.open(path, "r:*") as archive:
                names = [member.name for member in archive.getmembers() if member.isfile()]
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        return {"errors": [f"Archive could not be read: {exc}"], "warnings": warnings, "summary": summary}

    unsafe = [name for name in names if name.startswith("/") or ".." in Path(name).parts]
    if unsafe:
        errors.append("Archive contains unsafe paths.")

    netcdf_files = [name for name in names if name.lower().endswith(".nc")]
    doc_files = [name for name in names if name.lower().endswith(docs_ext)]
    summary["archive_members"] = len(names)
    summary["netcdf_files"] = len(netcdf_files)
    summary["documentation_files"] = len(doc_files)

    if not netcdf_files:
        errors.append("Archive does not contain any .nc files.")
    if not doc_files:
        warnings.append("Archive does not include a recognizable technical document.")

    return {"errors": errors, "warnings": warnings, "summary": summary}


def validate_submission(path, filename, metadata):
    kind = file_kind(filename)
    if kind == "netcdf":
        return validate_netcdf(path, filename, metadata)
    return validate_archive(path, filename, metadata)


def upload_record_public(row, include_validation=True):
    if isinstance(row, sqlite3.Row):
        row = dict(row)
    record = {
        "id": row["id"],
        "upload_id": row["upload_id"],
        "user_id": row["user_id"],
        "file_name": row["file_name"],
        "file_size": row["file_size"],
        "received_bytes": row["received_bytes"],
        "file_kind": row["file_kind"],
        "status": row["status"],
        "experiment": row["experiment"],
        "model": row["model"],
        "event": row["event"],
        "timestamp_utc": row["timestamp_utc"],
        "member": row["member"],
        "version": row["version"],
        "replaces_upload_id": row.get("replaces_upload_id"),
        "sha256": row["sha256"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_validation:
        record["validation"] = json.loads(row["validation_json"] or "{}")
    record["metadata"] = json.loads(row["metadata_json"] or "{}")
    return record


def constants_payload():
    return {
        "events": EVENTS,
        "experiments": EXPERIMENTS,
        "core_2d_vars": CORE_2D_VARS,
        "recommended_2d_vars": RECOMMENDED_2D_VARS,
        "three_d_vars": THREE_D_VARS,
        "chunk_size": MAX_CHUNK_BYTES,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "user_storage_quota_bytes": USER_STORAGE_QUOTA_BYTES,
    }
