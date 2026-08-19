import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import traceback
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from rumi_protocol import (  # noqa: F401  (re-exported for api.cgi, manage.py and tests)
    ARCHIVE_NAME_PATTERN,
    ARCHIVE_NAME_RE,
    ARCHIVE_TIME_ATTRS,
    CORE_2D_VARS,
    CORE_GRID,
    EVENTS,
    EXPERIMENTS,
    INIT_DIR_RE,
    INIT_LABELS,
    INIT_TIMES,
    OUTPUT_INTERVAL_HOURS,
    PHYSICS_ATTRS,
    RECOMMENDED_2D_VARS,
    REQUIRED_GLOBAL_ATTRS,
    REQUIRED_PERIODS,
    RULES_VERSION,
    RUMI_FILENAME_RE,
    RECOMMENDED_3D_ALTERNATIVES,
    RECOMMENDED_3D_LEVELS_HPA,
    RECOMMENDED_3D_LEVEL_VARS,
    RECOMMENDED_RADIATION_VARS,
    DOCUMENTATION_EXTENSIONS,
    INIT_TOLERANCE_HOURS,
    IssueLog,
    archive_stem,
    expected_initialization,
    init_label_is_valid,
    parse_rumi_filename,
    header_attr,
    header_dim,
    header_has_var,
    netcdf_facts_from_header,
    parse_lead_time_hours,
    validate_netcdf_facts,
    validate_timestamp_in_event,
    validate_archive_structure,
    validate_init_directory,
    SAFE_FILENAME_RE,
    THREE_D_VARS,
    expected_timestamps,
    init_time_for,
    iso_z,
    parse_absolute_init_label,
    parse_archive_name,
    parse_utc,
    required_period,
    resolution_category,
)


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
USER_STORAGE_QUOTA_BYTES = 250 * 1024 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 3000
MAX_ARCHIVE_NETCDF_FILES = 1500
MAX_ARCHIVE_EXPANDED_BYTES = MAX_UPLOAD_BYTES
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

IN_FLIGHT_UPLOAD_STATUSES = (
    "receiving",
    "queued",
    "validating",
)



class PortalError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
            institution TEXT NOT NULL,
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
    if "institution" not in upload_columns:
        con.execute("ALTER TABLE uploads ADD COLUMN institution TEXT")
        con.execute(
            """
            UPDATE uploads
            SET institution = (
                SELECT institution FROM users WHERE users.id = uploads.user_id
            )
            WHERE institution IS NULL OR institution = ''
            """
        )
    if "replaces_upload_id" not in upload_columns:
        con.execute("ALTER TABLE uploads ADD COLUMN replaces_upload_id TEXT")
    for column, definition in UPLOAD_COLUMN_ADDITIONS:
        if column not in upload_columns:
            con.execute(f"ALTER TABLE uploads ADD COLUMN {column} {definition}")
    user_columns = {
        row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()
    }
    for column, definition in USER_COLUMN_ADDITIONS:
        if column not in user_columns:
            con.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    con.execute("CREATE INDEX IF NOT EXISTS idx_uploads_institution ON uploads(institution)")
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_uploads_institution_event
            ON uploads(institution, event)
        """
    )
    con.commit()


USER_COLUMN_ADDITIONS = (
    # The point of contact and participant list belong to the account, so the
    # upload form does not have to ask for them on every submission.
    ("poc_surname", "TEXT"),
    ("participants", "TEXT"),
)

UPLOAD_COLUMN_ADDITIONS = (
    # Background validation progress, so the browser can show "213/512" while a
    # per-event archive is being checked.
    ("validation_done", "INTEGER NOT NULL DEFAULT 0"),
    ("validation_total", "INTEGER NOT NULL DEFAULT 0"),
    ("worker_pid", "INTEGER"),
    ("worker_heartbeat", "TEXT"),
    # Which rule set accepted the submission, so a later protocol change is
    # traceable per upload rather than only per deployment.
    ("rules_version", "TEXT"),
    # Configuration identity parsed from the v3 archive name.
    ("poc", "TEXT"),
    ("config_id", "TEXT"),
    ("archive_version", "TEXT"),
    ("participants", "TEXT"),
)


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
        "poc_surname": row.get("poc_surname") or "",
        "participants": row.get("participants") or "",
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


REFERENCE_NETCDF = BASE_DIR / "downloads" / "RUMI_template_2d.nc"

_ncdump_cache = None


def ncdump_candidates():
    return [
        os.environ.get("RUMI_NCDUMP"),
        "/usr/bin/ncdump",
        "/usr/local/bin/ncdump",
        shutil.which("ncdump"),
        "/home/lzhenn/array74/soft/anaconda3/bin/ncdump",
    ]


def ncdump_works(candidate):
    """Confirm a candidate can actually read a known-good NetCDF4 file.

    Some builds on the deployment host resolve but fail at load time with a
    missing glibc symbol. Without this check such a build would report every
    participant submission as unreadable, turning a server problem into a
    stream of misleading rejections.
    """
    if not REFERENCE_NETCDF.is_file():
        return True
    try:
        proc = run_command([candidate, "-k", str(REFERENCE_NETCDF)], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and "netCDF-4" in proc.stdout


def ncdump_executable():
    global _ncdump_cache
    if _ncdump_cache:
        return _ncdump_cache
    resolved = []
    for candidate in ncdump_candidates():
        if not candidate or candidate in resolved:
            continue
        if not (Path(candidate).is_file() and os.access(candidate, os.X_OK)):
            continue
        resolved.append(candidate)
        if ncdump_works(candidate):
            _ncdump_cache = candidate
            return candidate
    if resolved:
        raise PortalError(
            500,
            "NetCDF validation tool is installed but not working. "
            "No submission was checked.",
            {"rejected_candidates": resolved},
        )
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


def netcdf_coordinates(path):
    ncdump = ncdump_executable()
    proc = run_command(
        [ncdump, "-p", "15,15", "-v", "lat,lon", str(path)],
        timeout=90,
    )
    if proc.returncode != 0:
        raise PortalError(
            400,
            "Latitude/longitude coordinate extraction failed.",
            {"stderr": proc.stderr.strip()},
        )
    sections = proc.stdout.split("data:", 1)
    if len(sections) != 2:
        return {"lat": [], "lon": []}

    def values(name):
        match = re.search(
            r"(?:^|\n)\s*" + re.escape(name) + r"\s*=\s*(.*?);",
            sections[1],
            flags=re.DOTALL,
        )
        if not match:
            return []
        return [
            float(value)
            for value in re.findall(
                r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?",
                match.group(1),
            )
        ]

    return {"lat": values("lat"), "lon": values("lon")}


def validate_netcdf(path, filename, metadata):
    """Read one NetCDF file with ncdump and judge it against the shared rules.

    Only the reading happens here. The verdict comes from
    ``rumi_protocol.validate_netcdf_facts``, which is the same code the
    downloadable validator runs on the participant's own machine.
    """
    try:
        kind = netcdf_kind(path)
        header = netcdf_header(path)
        coordinates = netcdf_coordinates(path)
    except PortalError as exc:
        if exc.status >= 500:
            raise
        result = validate_netcdf_facts(filename, None, metadata)
        result["errors"].append(exc.message)
        if exc.details.get("stderr"):
            result["warnings"].append(exc.details["stderr"][:600])
        return result

    facts = netcdf_facts_from_header(kind, header, coordinates)
    return validate_netcdf_facts(filename, facts, metadata)


def validate_archive(path, filename, metadata, progress=None):
    """Validate a structured RUMI v3 submission archive.

    Structure is checked first from member paths alone, so naming and layout
    mistakes are reported in milliseconds. Per-file NetCDF checks only run once
    the layout is sound, because they cost roughly 0.2 s per file and a
    per-event archive holds several hundred of them.

    ``progress`` is an optional ``callable(done, total)`` used by the background
    validation worker to publish progress while it works.
    """
    errors = IssueLog()
    warnings = IssueLog()
    summary = {
        "rules_version": RULES_VERSION,
        "archive_members": 0,
        "netcdf_files": 0,
        "validated_netcdf_files": 0,
        "checked_netcdf_files": 0,
        "passed_netcdf_files": 0,
        "documentation_files": 0,
        "experiments": {},
    }

    def entry_name(entry):
        return entry.filename if hasattr(entry, "filename") else entry.name

    def entry_size(entry):
        return entry.file_size if hasattr(entry, "file_size") else entry.size

    def read_member(open_member, entry):
        with open_member(entry) as source:
            return source.read()

    def check_members(entries, open_member, archive_kind):
        names = [entry_name(entry) for entry in entries]
        netcdf_entries = [
            entry for entry in entries if entry_name(entry).lower().endswith(".nc")
        ]
        summary["archive_kind"] = archive_kind
        summary["archive_members"] = len(entries)
        summary["netcdf_files"] = len(netcdf_entries)

        if len(entries) > MAX_ARCHIVE_MEMBERS:
            errors.add(f"Archive contains more than {MAX_ARCHIVE_MEMBERS} files.")
        if len(netcdf_entries) > MAX_ARCHIVE_NETCDF_FILES:
            errors.add(
                f"Archive contains more than {MAX_ARCHIVE_NETCDF_FILES} NetCDF files."
            )
        if sum(entry_size(entry) for entry in entries) > MAX_ARCHIVE_EXPANDED_BYTES:
            errors.add("Archive expands beyond the permitted size.")
        if errors:
            return

        structure = validate_archive_structure(names, filename)
        summary["archive"] = structure["summary"].get("archive")
        summary["documentation_files"] = structure["summary"]["documentation_files"]
        for message in structure["errors"]:
            errors.add(message)
        for message in structure["warnings"]:
            warnings.add(message)

        manifest_entry = next(
            (
                entry
                for entry in entries
                if Path(entry_name(entry)).name == "rumi_manifest.json"
            ),
            None,
        )
        if manifest_entry is not None:
            try:
                manifest = json.loads(read_member(open_member, manifest_entry))
            except (OSError, ValueError) as exc:
                warnings.add(f"rumi_manifest.json could not be read: {exc}")
            else:
                summary["manifest"] = {
                    "rules_version": manifest.get("rules_version"),
                    "participants": manifest.get("participants"),
                    "validator_version": manifest.get("validator_version"),
                }
                if manifest.get("rules_version") != RULES_VERSION:
                    warnings.add(
                        f"rumi_manifest.json was written for rules version "
                        f"{manifest.get('rules_version')}, but this portal uses "
                        f"{RULES_VERSION}. Please download rumi_validate.py again."
                    )

        if errors:
            warnings.add(
                "Per-file checks were skipped because the archive layout must be "
                "corrected first."
            )
            return

        layout = structure["layout"]
        members_by_directory = {}
        total = len(layout)
        done = 0
        for entry in netcdf_entries:
            member_name = entry_name(entry)
            placement = layout.get(member_name)
            if placement is None:
                continue
            temporary_path = None
            try:
                with open_member(entry) as source:
                    with tempfile.NamedTemporaryFile(
                        dir=path.parent,
                        prefix="rumi-validate-",
                        suffix=".nc",
                        delete=False,
                    ) as temporary:
                        shutil.copyfileobj(source, temporary, length=1024 * 1024)
                        temporary_path = Path(temporary.name)
                # The experiment is a property of the directory the file sits
                # in, not of the archive: one archive carries several. Passing
                # the archive-level value here would compare every file against
                # the "(archive)" placeholder and reject the whole submission.
                member_metadata = dict(metadata)
                member_metadata["experiment"] = placement["experiment"]
                result = validate_netcdf(
                    temporary_path, placement["file_name"], member_metadata
                )
            except (OSError, RuntimeError, ValueError) as exc:
                errors.add(f"NetCDF file could not be read: {exc}", member_name)
                continue
            finally:
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)

            summary["validated_netcdf_files"] += 1
            summary["checked_netcdf_files"] += 1
            if not result["errors"]:
                summary["passed_netcdf_files"] += 1
            for message in result["errors"]:
                errors.add(message, member_name)
            for message in result["warnings"]:
                warnings.add(message, member_name)

            key = (placement["experiment"], placement["init"])
            members_by_directory.setdefault(key, []).append(
                {
                    "name": member_name,
                    "timestamp": placement["timestamp"],
                    "time_metadata": result["summary"].get("time_metadata") or {},
                }
            )
            done += 1
            if progress:
                progress(done, total)

        event = (summary.get("archive") or {}).get("event")
        for (experiment, init_label), members in sorted(members_by_directory.items()):
            directory = validate_init_directory(
                event, experiment, init_label, members
            )
            for message in directory["errors"]:
                errors.add(message)
            for message in directory["warnings"]:
                warnings.add(message)
            summary["experiments"].setdefault(experiment, {})[init_label] = (
                directory["coverage"]
            )

    lower = filename.lower()
    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                entries = [info for info in archive.infolist() if not info.is_dir()]
                check_members(entries, archive.open, "zip")
        else:
            with tarfile.open(path, "r:*") as archive:
                entries = [member for member in archive.getmembers() if member.isfile()]

                def archive_opener(entry):
                    source = archive.extractfile(entry)
                    if source is None:
                        raise OSError("Archive member is unavailable.")
                    return source

                check_members(entries, archive_opener, "tar")
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        return {
            "errors": [f"Archive could not be read: {exc}"],
            "warnings": warnings.messages(),
            "summary": summary,
        }

    return {
        "errors": errors.messages(),
        "warnings": warnings.messages(),
        "summary": summary,
    }


def validate_submission(path, filename, metadata):
    kind = file_kind(filename)
    if kind == "netcdf":
        return validate_netcdf(path, filename, metadata)
    return validate_archive(path, filename, metadata)


def remove_upload_files(row):
    """Delete an upload's stored and temporary files, then prune empty parents."""
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


def log_exception(exc, context=""):
    """Record a traceback and return a short reference to quote to the user."""
    request_id = secrets.token_hex(6)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "api_errors.log", "a", encoding="utf-8") as handle:
            handle.write(
                f"\n[{utcnow()}] request_id={request_id} context={context} "
                f"type={type(exc).__name__}\n"
            )
            handle.write(traceback.format_exc())
    except Exception:
        pass
    return request_id


def storage_directory(row):
    """Where an accepted submission is filed.

    A v3 archive spans several experiments, so it is filed by event and model.
    Single NetCDF files keep the original four-level path so existing
    submissions stay where the database says they are.
    """
    institution = slugify(row["institution"])
    if row["file_kind"] in ("zip", "tar"):
        return SUBMISSIONS_DIR / institution / row["event"] / slugify(row["model"])
    return (
        SUBMISSIONS_DIR
        / institution
        / slugify(row["experiment"])
        / slugify(row["model"])
        / row["event"]
    )


def finalize_upload(con, row, validation, digest):
    """Record the outcome of a validated upload and, if accepted, store it.

    Shared by the CGI (single NetCDF files, validated inline) and by the
    background worker (archives), so an archive and a single file cannot drift
    apart on duplicate handling, storage layout, or supersession.
    Returns the refreshed upload row.
    """
    upload_id = row["upload_id"]
    now = utcnow()

    def refresh():
        return con.execute(
            "SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)
        ).fetchone()

    if validation.get("errors"):
        con.execute(
            """
            UPDATE uploads
            SET status = 'rejected', sha256 = ?, validation_json = ?,
                rules_version = ?, updated_at = ?, worker_pid = NULL
            WHERE upload_id = ?
            """,
            (digest, json.dumps(validation, ensure_ascii=True), RULES_VERSION, now, upload_id),
        )
        con.commit()
        return refresh()

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
            row["user_id"],
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
        con.execute(
            """
            UPDATE uploads
            SET status = 'duplicate', temp_path = NULL, sha256 = ?,
                validation_json = ?, rules_version = ?, updated_at = ?,
                worker_pid = NULL
            WHERE upload_id = ?
            """,
            (digest, json.dumps(validation, ensure_ascii=True), RULES_VERSION, now, upload_id),
        )
        con.commit()
        return refresh()

    temp_path = Path(row["temp_path"])
    final_dir = storage_directory(row)
    final_path = final_dir / (upload_id + "_" + safe_file_name(row["file_name"]))
    inactive_placeholders = ", ".join("?" for _ in INACTIVE_UPLOAD_STATUSES)
    try:
        final_dir.mkdir(parents=True, exist_ok=True)
        temp_path.replace(final_path)
        con.execute(
            """
            UPDATE uploads
            SET status = 'validated', stored_path = ?, temp_path = NULL, sha256 = ?,
                validation_json = ?, rules_version = ?, updated_at = ?,
                worker_pid = NULL
            WHERE upload_id = ?
            """,
            (
                str(final_path),
                digest,
                json.dumps(validation, ensure_ascii=True),
                RULES_VERSION,
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
                (now, row["replaces_upload_id"], row["user_id"], *INACTIVE_UPLOAD_STATUSES),
            )
        con.commit()
    except Exception as exc:
        request_id = log_exception(exc, context=f"finalize:{upload_id}")
        validation["errors"] = [
            "The file passed validation, but the server could not finalize it. "
            f"No submission was accepted. Reference: {request_id}"
        ]
        con.execute(
            """
            UPDATE uploads
            SET status = 'server_error', sha256 = ?, validation_json = ?,
                updated_at = ?, worker_pid = NULL
            WHERE upload_id = ?
            """,
            (digest, json.dumps(validation, ensure_ascii=True), now, upload_id),
        )
        con.commit()
    return refresh()


def reap_stale_validations(con, older_than_minutes=30):
    """Fail validations whose worker stopped reporting.

    Called opportunistically from ordinary requests. The worker runs on the web
    host while the only crontab lives on a different machine, so a scheduled
    reaper would mean a second host writing this SQLite file over NFS.
    """
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=older_than_minutes)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = con.execute(
        """
        SELECT * FROM uploads
        WHERE status IN ('queued', 'validating')
          AND COALESCE(worker_heartbeat, updated_at) < ?
        """,
        (cutoff,),
    ).fetchall()
    for row in rows:
        validation = {
            "errors": [
                "Validation stopped unexpectedly and no submission was accepted. "
                "Please upload the archive again."
            ],
            "warnings": [],
            "summary": {},
        }
        con.execute(
            """
            UPDATE uploads
            SET status = 'server_error', validation_json = ?, updated_at = ?,
                worker_pid = NULL
            WHERE upload_id = ?
            """,
            (json.dumps(validation, ensure_ascii=True), utcnow(), row["upload_id"]),
        )
    if rows:
        con.commit()
    return len(rows)


def upload_record_public(row, include_validation=True):
    if isinstance(row, sqlite3.Row):
        row = dict(row)
    record = {
        "id": row["id"],
        "upload_id": row["upload_id"],
        "user_id": row["user_id"],
        "institution": row.get("institution") or row.get("uploader_institution") or "",
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
        "validation_done": row.get("validation_done") or 0,
        "validation_total": row.get("validation_total") or 0,
        "rules_version": row.get("rules_version") or "",
        "poc": row.get("poc") or "",
        "config_id": row.get("config_id") or "",
        "archive_version": row.get("archive_version") or "",
        "participants": row.get("participants") or "",
        "sha256": row["sha256"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_validation:
        record["validation"] = json.loads(row["validation_json"] or "{}")
    record["metadata"] = json.loads(row["metadata_json"] or "{}")
    if row.get("uploader_name"):
        record["uploader"] = {
            "name": row["uploader_name"],
            "email": row.get("uploader_email") or "",
            "institution": row.get("uploader_institution") or "",
        }
    return record


def constants_payload():
    return {
        "events": EVENTS,
        "experiments": EXPERIMENTS,
        "core_2d_vars": CORE_2D_VARS,
        "recommended_2d_vars": RECOMMENDED_2D_VARS,
        "three_d_vars": THREE_D_VARS,
        "recommended_radiation_vars": RECOMMENDED_RADIATION_VARS,
        "recommended_3d_level_vars": RECOMMENDED_3D_LEVEL_VARS,
        "recommended_3d_alternatives": [list(a) for a in RECOMMENDED_3D_ALTERNATIVES],
        "recommended_3d_levels_hpa": RECOMMENDED_3D_LEVELS_HPA,
        "rules_version": RULES_VERSION,
        "required_periods": REQUIRED_PERIODS,
        "init_times": INIT_TIMES,
        "init_labels": INIT_LABELS,
        "archive_name_pattern": ARCHIVE_NAME_PATTERN,
        "output_interval_hours": OUTPUT_INTERVAL_HOURS,
        "chunk_size": MAX_CHUNK_BYTES,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "user_storage_quota_bytes": USER_STORAGE_QUOTA_BYTES,
    }
