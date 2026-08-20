#!/home/lzhenn/array74/soft/anaconda3/bin/python3
"""Validate a submitted archive outside the web request.

A per-event RUMI archive holds several hundred NetCDF files and takes minutes
to check, while the web server's request timeout is 60 seconds. `api.cgi`
therefore stores the upload, marks it `queued`, and starts this script in its
own session; the browser follows along through the `upload_status` action.

Run as:  python3 validate_worker.py --upload-id <id>
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portal_lib import (  # noqa: E402
    connect_db,
    finalize_upload,
    log_exception,
    sha256_file,
    upload_record_public,
    utcnow,
    validate_archive,
)

import json  # noqa: E402

HEARTBEAT_EVERY_FILES = 20
HEARTBEAT_EVERY_SECONDS = 20.0


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


def validate_upload(upload_id):
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
        elapsed = time.time() - started
        summary = validation.get("summary", {})
        print(
            f"upload_id={upload_id} status={record['status']} "
            f"files={summary.get('checked_netcdf_files', 0)} "
            f"passed={summary.get('passed_netcdf_files', 0)} "
            f"errors={len(validation.get('errors', []))} "
            f"seconds={elapsed:.1f}"
        )
        return 0


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
