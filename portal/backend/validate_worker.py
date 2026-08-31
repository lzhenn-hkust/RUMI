#!/home/lzhenn/array74/soft/anaconda3/bin/python3
"""Validate a submitted archive outside the web request.

A per-event RUMI archive holds several hundred NetCDF files and takes minutes
to check, while the web server's request timeout is 60 seconds. `api.cgi`
therefore stores the upload, marks it `queued`, and starts this script in its
own session; the browser follows along through the `upload_status` action.

Run as:  python3 validate_worker.py --upload-id <id>
"""
import argparse
from contextlib import contextmanager
import fcntl
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portal_lib import (  # noqa: E402
    connect_db,
    extract_archive,
    finalize_upload,
    log_exception,
    LOG_DIR,
    PRIVATE_DIR_MODE,
    PRIVATE_FILE_MODE,
    set_extraction_status,
    sha256_file,
    upload_record_public,
    utcnow,
    validate_archive,
)

import json  # noqa: E402

HEARTBEAT_EVERY_FILES = 20
HEARTBEAT_EVERY_SECONDS = 20.0


@contextmanager
def validation_slot():
    """Serialize archive validation so uploads cannot spawn unlimited ncdump work."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LOG_DIR.chmod(PRIVATE_DIR_MODE)
    except OSError:
        pass
    fd = os.open(
        LOG_DIR / "validation.lock",
        os.O_RDWR | os.O_CREAT,
        PRIVATE_FILE_MODE,
    )
    try:
        try:
            os.fchmod(fd, PRIVATE_FILE_MODE)
        except PermissionError:
            pass
        lock = os.fdopen(fd, "a+", encoding="ascii")
    except Exception:
        os.close(fd)
        raise
    with lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def claim(con, upload_id):
    """Take ownership of a queued upload.

    The update is conditional on the row still being `queued`, so a duplicate
    launch of this worker exits instead of validating the same archive twice.
    """
    now = utcnow()
    cursor = con.execute(
        """
        UPDATE uploads
        SET status = 'validating', worker_pid = ?, worker_heartbeat = ?, updated_at = ?
        WHERE upload_id = ? AND status = 'queued'
        """,
        (os.getpid(), now, now, upload_id),
    )
    con.commit()
    if cursor.rowcount != 1:
        return None
    return con.execute(
        "SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)
    ).fetchone()


def make_progress_reporter(con, upload_id):
    state = {"last": 0.0}

    def report(done, total):
        now = time.monotonic()
        if (
            done % HEARTBEAT_EVERY_FILES
            and now - state["last"] < HEARTBEAT_EVERY_SECONDS
            and done != total
        ):
            return
        state["last"] = now
        con.execute(
            """
            UPDATE uploads
            SET validation_done = ?, validation_total = ?, worker_heartbeat = ?,
                updated_at = ?
            WHERE upload_id = ?
            """,
            (done, total, utcnow(), utcnow(), upload_id),
        )
        con.commit()

    return report


def record_server_error(con, upload_id, message):
    validation = {"errors": [message], "warnings": [], "summary": {}}
    con.execute(
        """
        UPDATE uploads
        SET status = 'server_error', validation_json = ?, updated_at = ?,
            worker_pid = NULL
        WHERE upload_id = ?
        """,
        (json.dumps(validation, ensure_ascii=True), utcnow(), upload_id),
    )
    con.commit()


def make_extraction_reporter(con, upload_id):
    state = {"last": 0.0}

    def report(done, total):
        now = time.monotonic()
        if done != total and now - state["last"] < HEARTBEAT_EVERY_SECONDS:
            return
        state["last"] = now
        con.execute(
            "UPDATE uploads SET worker_heartbeat = ?, updated_at = ? WHERE upload_id = ?",
            (utcnow(), utcnow(), upload_id),
        )
        con.commit()

    return report


def validate_upload(upload_id):
    with validation_slot():
        return _validate_upload(upload_id)


def _validate_upload(upload_id):
    with connect_db() as con:
        row = claim(con, upload_id)
        if row is None:
            print(f"upload_id={upload_id} was not queued; nothing to do")
            return 0

        temp_path = Path(row["temp_path"]) if row["temp_path"] else None
        if not temp_path or not temp_path.exists():
            record_server_error(
                con,
                upload_id,
                "The uploaded file was no longer available when validation "
                "started. No submission was accepted.",
            )
            return 1

        started = time.time()
        try:
            digest = sha256_file(temp_path)
            validation = validate_archive(
                temp_path,
                row["file_name"],
                json.loads(row["metadata_json"] or "{}"),
                progress=make_progress_reporter(con, upload_id),
            )
        except Exception as exc:  # noqa: BLE001 - the outcome must be recorded
            request_id = log_exception(exc, context=f"worker:{upload_id}")
            record_server_error(
                con,
                upload_id,
                "The server could not validate this archive. No submission was "
                f"accepted. Reference: {request_id}",
            )
            return 1

        record = finalize_upload(con, row, validation, digest)
        extraction_error = None
        if record["status"] == "validated" and record["file_kind"] in ("zip", "tar"):
            try:
                set_extraction_status(con, upload_id, "extracting")
                details = extract_archive(
                    record,
                    heartbeat=make_extraction_reporter(con, upload_id),
                )
                set_extraction_status(con, upload_id, "ready", details=details)
            except Exception as exc:  # noqa: BLE001 - retain the accepted archive
                request_id = log_exception(exc, context=f"extract:{upload_id}")
                extraction_error = (
                    "The archive passed validation and was stored, but its analysis "
                    "copy could not be prepared. "
                    f"Reference: {request_id}"
                )
                set_extraction_status(
                    con,
                    upload_id,
                    "failed",
                    error=extraction_error,
                )
        elapsed = time.time() - started
        summary = validation.get("summary", {})
        print(
            f"upload_id={upload_id} status={record['status']} "
            f"files={summary.get('checked_netcdf_files', 0)} "
            f"passed={summary.get('passed_netcdf_files', 0)} "
            f"extraction={record['extraction_status'] if not extraction_error else 'failed'} "
            f"errors={len(validation.get('errors', []))} "
            f"seconds={elapsed:.1f}"
        )
        return 1 if extraction_error else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="RUMI background archive validation")
    parser.add_argument("--upload-id", required=True)
    args = parser.parse_args(argv)
    try:
        return validate_upload(args.upload_id)
    except Exception as exc:  # noqa: BLE001 - never die silently
        log_exception(exc, context=f"worker-main:{args.upload_id}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
