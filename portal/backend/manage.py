#!/home/lzhenn/array74/soft/anaconda3/bin/python3
import argparse
import secrets
import sys
from pathlib import Path

from portal_lib import (
    DATA_DIR,
    reap_stale_validations,
    connect_db,
    ensure_registration_code,
    hash_password,
    import_whitelist,
    load_whitelist_file,
    normalize_email,
    set_setting,
    utcnow,
)


def init(args):
    with connect_db() as con:
        emails = load_whitelist_file(args.whitelist)
        import_whitelist(con, emails, source="Email List.docx")
        registration_code = ensure_registration_code(con)

        email = normalize_email(args.admin_email)
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        password = None
        if row:
            con.execute(
                "UPDATE users SET role = 'admin', status = 'approved', updated_at = ? WHERE email = ?",
                (utcnow(), email),
            )
        else:
            password = args.admin_password or secrets.token_urlsafe(12)
            salt, digest = hash_password(password)
            now = utcnow()
            con.execute(
                """
                INSERT INTO whitelist(email, source, created_at)
                VALUES (?, 'admin', ?)
                ON CONFLICT(email) DO NOTHING
                """,
                (email, now),
            )
            con.execute(
                """
                INSERT INTO users(email, name, institution, role, status, password_salt, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, 'admin', 'approved', ?, ?, ?, ?)
                """,
                (
                    email,
                    args.admin_name,
                    args.admin_institution,
                    salt,
                    digest,
                    now,
                    now,
                ),
            )
        con.commit()

        print(f"whitelist_count={len(emails)}")
        print(f"admin_email={email}")
        print(f"registration_code={registration_code}")
        if password:
            print(f"admin_initial_password={password}")
        else:
            print("admin_existing=1")


def reset_password(args):
    with connect_db() as con:
        email = normalize_email(args.email)
        password = args.password or secrets.token_urlsafe(12)
        salt, digest = hash_password(password)
        now = utcnow()
        cur = con.execute(
            """
            UPDATE users
            SET password_salt = ?, password_hash = ?, updated_at = ?, status = 'approved'
            WHERE email = ?
            """,
            (salt, digest, now, email),
        )
        con.execute(
            """
            INSERT INTO whitelist(email, source, created_at)
            VALUES (?, 'admin', ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (email, now),
        )
        con.commit()
        if cur.rowcount == 0:
            print(f"user_not_found={email}", file=sys.stderr)
            return 1
        print(f"email={email}")
        print(f"new_password={password}")
    return 0


def status(args):
    with connect_db() as con:
        users = con.execute("SELECT status, COUNT(*) AS c FROM users GROUP BY status").fetchall()
        uploads = con.execute("SELECT status, COUNT(*) AS c FROM uploads GROUP BY status").fetchall()
        whitelist = con.execute("SELECT COUNT(*) AS c FROM whitelist").fetchone()["c"]
        print(f"whitelist={whitelist}")
        for row in users:
            print(f"users.{row['status']}={row['c']}")
        for row in uploads:
            print(f"uploads.{row['status']}={row['c']}")


def delete_upload(args):
    with connect_db() as con:
        base = DATA_DIR
        row = con.execute(
            "SELECT stored_path, temp_path FROM uploads WHERE upload_id = ?",
            (args.upload_id,),
        ).fetchone()
        if row:
            for value in (row["stored_path"], row["temp_path"]):
                if not value:
                    continue
                path = Path(value)
                try:
                    path.relative_to(base)
                except ValueError:
                    continue
                if path.exists():
                    path.unlink()
        con.execute("DELETE FROM uploads WHERE upload_id = ?", (args.upload_id,))
        if args.clear_sessions:
            con.execute("DELETE FROM sessions")
        con.commit()
    print(f"deleted_upload={args.upload_id}")


def approve_whitelisted_pending(args):
    with connect_db() as con:
        now = utcnow()
        cur = con.execute(
            """
            UPDATE users
            SET status = 'approved', updated_at = ?
            WHERE status = 'pending'
              AND email IN (SELECT email FROM whitelist)
            """,
            (now,),
        )
        con.commit()
    print(f"approved_pending={cur.rowcount}")


def reap_validations(args):
    """Fail archive validations whose worker stopped reporting.

    Ordinary portal requests already do this opportunistically; this command is
    for an administrator who wants to clear them immediately.
    """
    with connect_db() as con:
        count = reap_stale_validations(con, args.older_than_minutes)
    print(f"reaped_stale_validations={count}")


def registration_code(args):
    with connect_db() as con:
        if args.reset:
            import secrets

            code = "RUMI-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "")[:12]
            set_setting(con, "registration_code", code)
        else:
            code = ensure_registration_code(con)
    print(f"registration_code={code}")


def main():
    parser = argparse.ArgumentParser(description="RUMI portal maintenance")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--admin-email", required=True)
    p_init.add_argument("--admin-name", required=True)
    p_init.add_argument("--admin-institution", required=True)
    p_init.add_argument("--admin-password")
    p_init.add_argument("--whitelist")
    p_init.set_defaults(func=init)

    p_reset = sub.add_parser("reset-password")
    p_reset.add_argument("--email", required=True)
    p_reset.add_argument("--password")
    p_reset.set_defaults(func=reset_password)

    p_status = sub.add_parser("status")
    p_status.set_defaults(func=status)

    p_delete = sub.add_parser("delete-upload")
    p_delete.add_argument("--upload-id", required=True)
    p_delete.add_argument("--clear-sessions", action="store_true")
    p_delete.set_defaults(func=delete_upload)

    p_approve = sub.add_parser("approve-whitelisted-pending")
    p_approve.set_defaults(func=approve_whitelisted_pending)

    p_reap = sub.add_parser("reap-stale-validations")
    p_reap.add_argument("--older-than-minutes", type=int, default=30)
    p_reap.set_defaults(func=reap_validations)

    p_code = sub.add_parser("registration-code")
    p_code.add_argument("--reset", action="store_true")
    p_code.set_defaults(func=registration_code)

    args = parser.parse_args()
    result = args.func(args)
    raise SystemExit(result or 0)


if __name__ == "__main__":
    main()
