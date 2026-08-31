# RUMI Portal Persistent Context

Last verified: 2026-08-31

## Local Repository

- Workspace: `/Users/zhenningli/work/ust-jumper/RUMI`
- Git remote: `github-hkust:lzhenn-hkust/RUMI.git`
- Main branch: `main`
- Do not commit runtime databases, uploaded data, private portal data, or local path configuration.

## Topology (corrected 2026-08-18 by live probe — the earlier note was wrong)

The portal does **not** execute on `hqlx74`.

| Role | Host | User | Notes |
|---|---|---|---|
| Runs the CGI and the validation worker | `envf.ust.hk` | `apache` | Python 3.10.14, 24 cores, `/usr/bin/ncdump`, `setsid` present |
| File management, deployment target, shell access | `hqlx74` | `lzhenn` | reached via `mini`; NFS-mounts the same site tree |

`hqlx74` and `envf.ust.hk` share the site directory over NFS, which is why
deploying from `hqlx74` works. But anything about *runtime* behaviour — the
process user, available tooling, timing measurements — must be judged on
`envf.ust.hk`, not on `hqlx74`.

Consequences that are easy to get wrong:

- Files the portal writes are owned by `apache:apache`. The private data
  directory carries ACLs that keep `lzhenn` able to read and delete them.
- `/tmp` is **not** shared between the two hosts.
- The only user crontab is on `hqlx74` as `lzhenn`, a different machine from the
  worker. Do **not** schedule anything there that writes the portal SQLite file:
  that would mean a second host writing the same database over NFS. Stale
  validations are reaped opportunistically inside ordinary CGI requests instead
  (`portal_lib.reap_stale_validations`), with
  `manage.py reap-stale-validations` kept only as a manual admin command.
- Apache 2.4.6, and `httpd.conf` sets no `Timeout`, so the default 60 s applies.
  This is why archive validation runs in a detached worker rather than inline.

Verified by probe on 2026-08-18: a CGI that starts a child with
`start_new_session=True` returns in 0.73 s and the child is still alive 75 s
later. Probe files were deleted afterwards.

## NetCDF tooling

- `portal_lib.ncdump_executable()` resolves `/usr/bin/ncdump` on both hosts.
- The anaconda build at `/home/lzhenn/array74/soft/anaconda3/bin/ncdump` is
  **broken on hqlx74** (`GLIBC_2.25 not found`). It is still in the candidate
  list as a last resort, so `ncdump_executable()` now self-checks each candidate
  against `downloads/RUMI_template_2d.nc` and raises a 500 if none works —
  without that check, a broken ncdump would reject every participant submission
  with a misleading "file is unreadable" message.

## SSH Access

- Shell access is through the `mini` jump host and then `hqlx74`.
- Account on `hqlx74`: `lzhenn`; root access is unavailable.
- Typical command form:

  ```bash
  ssh mini 'ssh -tt hqlx74 "<command>"'
  ```

- `hqlx54` is available for NetCDF validation when the software environment on `hqlx74` has compatibility issues.

## Web Portal Location

- Production URL: `https://envf.ust.hk/dataview/RUMI/`
- Legacy URL: `https://envf.ust.hk/dataview/test/lzn/RUMI/` (Apache 308
  redirect to the production URL)
- User-facing site path: `/home/lzhenn/RUMI/`
- `/home/lzhenn/RUMI` is a symlink to `/home/dataop/data/nmodel/RUMI/`, which resolves to `/disk/rtbuf1/nmodel/RUMI` on `hqlx74`.
- Web files are directly under the symlink target root. There is no `portal/` subdirectory on the server.
- Expected server layout:
  - `/home/lzhenn/RUMI/index.html`
  - `/home/lzhenn/RUMI/api.cgi`
  - `/home/lzhenn/RUMI/assets/`
  - `/home/lzhenn/RUMI/backend/`
  - `/home/lzhenn/RUMI/downloads/`
  - `/home/lzhenn/RUMI/data/`

## Private Runtime Data

- Compatibility path used by the application: `/home/lzhenn/RUMI_portal_private/`
- The compatibility path is now a symlink to `/disk/rtbuf1/nmodel/RUMI/.portal_private/`.
- Actual private data root and quota-bearing location: `/disk/rtbuf1/nmodel/RUMI/.portal_private/`
- The private directory is inside the site tree but has its own `.htaccess` denying Web access; verify the denial after any deployment change.
- `/home/lzhenn/RUMI/backend/data_dir.txt` contains this private data path.
- SQLite database: `/disk/rtbuf1/nmodel/RUMI/.portal_private/rumi_portal.sqlite3`
- Temporary upload chunks: `/disk/rtbuf1/nmodel/RUMI/.portal_private/incoming/`
- Accepted submission files: `/disk/rtbuf1/nmodel/RUMI/.portal_private/submissions/`
- API error log: `/disk/rtbuf1/nmodel/RUMI/.portal_private/logs/api_errors.log`
- SQLite backups are stored alongside the database with timestamped names.
- The pre-migration home-directory copy is retained temporarily at `/home/lzhenn/RUMI_portal_private.migration-backup-20260817` for rollback.
- Never expose or commit this directory.
- Before deleting files in `incoming/`, check the corresponding `uploads.temp_path` and status in SQLite. Rejected uploads can leave large temporary files behind.

## Backups — read this before running one

`/home/lzhenn/RUMI` is a symlink, and **`.portal_private` sits inside it**. A
plain `tar -C /home/lzhenn/RUMI .` therefore sweeps up every participant
submission: it produced a 2.1 GB archive inside a home directory with a 20 GB
quota. Back up the code only:

```bash
ssh mini 'ssh hqlx74 "tar -czf /home/lzhenn/RUMI-code-backup-<stamp>.tar.gz \
    --exclude=.portal_private --exclude=__pycache__ --exclude=./data \
    -C /home/lzhenn/RUMI ."'
```

That is ~50 KB and still captures the server-only `backend/data_dir.txt` and
`backend/whitelist_emails.txt`, which are not in Git and must never be
overwritten by a release.

## Releases are built on macOS — disable AppleDouble

`tar` on macOS writes `._*` resource-fork files into the archive, and they had
been accumulating in the site root across past deployments. Always build with:

```bash
COPYFILE_DISABLE=1 tar -czf /tmp/rumi-release.tar.gz portal/...
```

## Stage before overwriting

Extract the release into `/tmp/rumi-stage` and run
`py_compile` there with the server interpreter *before* extracting over the live
site. Local development is on Python 3.13 while the server is 3.10, so this is
the only place 3.11+ syntax would be caught.

## Storage Quota

- `/disk/rtbuf1` is `hqlx123.ust.hk:/export/v123.rtbuf1`, a 16 TB NFS filesystem with about 5 TB free at the last check.
- No user or group quota was reported for the `/disk/rtbuf1` mount from `hqlx74`; confirm any project policy with `dataop` before assuming the full free space is available.
- The old `/home/lzhenn` filesystem has a 20 GB user quota. The migration backup temporarily remains there and should be removed only after rollback confidence is no longer needed.

## Deployment Procedure

1. Build a release archive locally with paths beginning with `portal/`, containing only changed runtime files, for example:

   ```bash
   tar -czf /tmp/rumi-release.tar.gz \
       portal/api.cgi \
       portal/index.html \
       portal/assets/app.js portal/assets/styles.css \
       portal/backend/portal_lib.py \
       portal/backend/rumi_protocol.py \
       portal/backend/validate_worker.py \
       portal/backend/manage.py \
       portal/downloads/rumi_validate.py \
       portal/downloads/create_ncdf.py \
       portal/downloads/RUMI_template_2d.nc
   ```

   Run `python3 tools/build_validator.py` and `python3 tools/sync_downloads.py`
   before packaging: `portal/downloads/` is what participants receive and is
   generated from the repository-root sources.

   `rumi_protocol.py` and `validate_worker.py` are new in the v3 protocol work
   and the portal will not start without the former. `downloads/rumi_validate.py`
   is generated — run `python3 tools/build_validator.py` before packaging, and
   `python3 tools/build_validator.py --check` fails the test suite if it is
   stale.

2. Copy it to `mini`, then to `hqlx74`:

   ```bash
   scp /tmp/rumi-release.tar.gz mini:/tmp/rumi-release.tar.gz
   ssh mini 'scp /tmp/rumi-release.tar.gz hqlx74:/tmp/rumi-release.tar.gz'
   ```

3. Before extraction, back up the code and the private SQLite database. Use the
   excludes from "Backups — read this before running one" above: without them
   this step copies every participant submission into a quota-bearing home.

   ```bash
   ssh mini 'ssh hqlx74 "tar -czf /home/lzhenn/RUMI-code-backup-<stamp>.tar.gz --exclude=.portal_private --exclude=__pycache__ --exclude=./data -C /home/lzhenn/RUMI ."'
   ssh mini 'ssh hqlx74 "cp -p /home/lzhenn/RUMI_portal_private/rumi_portal.sqlite3 /home/lzhenn/RUMI_portal_private/rumi_portal.sqlite3.backup-<stamp>"'
   ```

4. Stage first, then extract with `--strip-components=1` because the local
   archive has a `portal/` prefix but the server files belong at the site root:

   ```bash
   ssh mini 'ssh hqlx74 "rm -rf /tmp/rumi-stage && mkdir -p /tmp/rumi-stage && tar -xzf /tmp/rumi-release.tar.gz --strip-components=1 -C /tmp/rumi-stage && cd /tmp/rumi-stage && /home/lzhenn/array74/soft/anaconda3/bin/python3 -m py_compile backend/*.py"'
   ssh mini 'ssh hqlx74 "tar -xzf /tmp/rumi-release.tar.gz --strip-components=1 -C /home/lzhenn/RUMI"'
   ```

   Compare the staged SHA-256 against the local file before overwriting the
   live site, and clean up `/tmp/rumi-stage` afterwards.

5. Verify the public index and API, compare SHA-256 hashes, and confirm the
   SQLite schema after the first API request. The API applies additive schema
   migrations automatically (`portal_lib.UPLOAD_COLUMN_ADDITIONS` and
   `USER_COLUMN_ADDITIONS`); confirm the new columns exist:

   Nested-ssh quoting makes one-liners unreadable and easy to get wrong. Pipe a
   script over stdin instead:

   ```bash
   ssh mini 'ssh hqlx74 "/home/lzhenn/array74/soft/anaconda3/bin/python3 -"' < check_schema.py
   ```

   where `check_schema.py` inserts `/home/lzhenn/RUMI/backend` on `sys.path`,
   calls `portal_lib.connect_db()`, and prints whether every column named in
   `portal_lib.UPLOAD_COLUMN_ADDITIONS` and `USER_COLUMN_ADDITIONS` is present.
   An `AttributeError` on those names means the release did not actually land.

6. Because the code must run on Python 3.10 while local development is on 3.13,
   compile on the server before trusting a release:

   ```bash
   ssh mini 'ssh hqlx74 "cd /home/lzhenn/RUMI && /home/lzhenn/array74/soft/anaconda3/bin/python3 -m py_compile api.cgi backend/*.py downloads/rumi_validate.py"'
   ```

7. Re-confirm that `/home/lzhenn/RUMI_portal_private/.htaccess` still denies web
   access, and that no probe or scratch files remain in the site root.

## Current Data Organization

New accepted files are stored as:

Single NetCDF files (unchanged):

`submissions/<institution>/<experiment>/<model>/<event>/<upload_id>_<file-name>`

v3 event archives, which span several experiments and so cannot be filed under
one of them:

`submissions/<institution>/<event>/<model>/<upload_id>_<archive-name>`

The SQLite database is the authoritative index. Institution is stored as a submission-time snapshot; changing a user's profile does not rewrite historical attribution or paths. Older submissions may retain their original storage path.


## Deployment log

- **2026-08-31** — RUMI protocol v3.2
  (`RULES_VERSION: 2026-08-rumi-v3.2`) deployed from Git commit `6d805b6`.
  Archive names now accept optional configuration and ensemble-member suffixes
  in the fixed form
  `<INST>-<MODEL>-<EVENT>-<POC>[-CONFIG<NN>][-MEM<NN>].tar.gz|zip`.
  The API stores them in the existing `config_id` and `member` columns and
  includes both in the derived analysis manifest. The old archive-wide limit
  of 1500 NetCDF files was removed; the total archive member safety limit is
  now 6000 and the 20 GiB compressed/expanded limits remain.
  Verified after deploy: 145 local tests passed; production frontend and
  backend parse all four optional-suffix combinations; SQLite
  `integrity_check` is `ok` with 31 uploads / 4 users intact; participant
  validator/template downloads match local SHA-256; the private tree returns
  403; and the legacy URL redirects to production.
  Backups: `/home/lzhenn/RUMI-code-backup-20260831-191625.tar.gz` and
  `rumi_portal.sqlite3.backup-20260831-191625`.

- **2026-08-19** — RUMI protocol v3 (`RULES_VERSION: 2026-08-rumi-v3`) deployed.
  Per-event archives, `Init-*` directories replacing `lead_NNNh`, background
  archive validation with progress polling, resumable uploads, simplified upload
  form, downloadable `rumi_validate.py`. Naming dropped the `RUMI-` prefix and
  moved the version token from `v` to `r`. Radiation and pressure-level
  variables are recommended (reported, never rejected); the nine core 2D
  variables remain required.
  Verified after deploy: schema migration added all new `uploads`/`users`
  columns with 23 uploads / 4 users / 61 whitelist entries intact; every private
  path returns 403; the three participant downloads serve the new versions; the
  browser accepts a v3 archive name and rejects the legacy prefixed form.
  Backups: `/home/lzhenn/RUMI-code-backup-20260819-113231.tar.gz` and
  `rumi_portal.sqlite3.backup-20260819-113231`.

- **2026-08-19 (later the same day)** — Two defects found by running the real
  pipeline against real NetCDF, after the v3 release above had already been
  verified structurally.

  1. Every archive submission was being rejected. `api.cgi` writes
     `experiment = "(archive)"` on an archive upload row, because one archive
     spans several experiments and the column holds one value;
     `validate_archive` passed that archive-level metadata to every member, so
     each file's `ERA5-AN` was compared against the placeholder. Fixed by
     reading the experiment from the member's own directory. Nothing caught it
     because every archive test patches `validate_netcdf`, and the shipped
     validator walks directories and has no upload row, so it passed the same
     archive.
  2. `downloads/rumi_validate.py` reported "NetCDF file could not be read" for
     every file when the broken anaconda ncdump was first on PATH. It now
     probes each candidate with a no-argument usage check and falls back to
     `/usr/bin/ncdump`; when none runs it exits 2 naming the linker error.

  Both now covered by tests that use real NetCDF files and fail if the fixes
  are reverted, including one asserting the portal and `rumi_validate.py` reach
  the same verdict on the same archive.

  Verified on the server after deploy: the portal accepts a well-formed archive
  (12/12 files) and rejects one missing its required final timestamp;
  `rumi_validate.py` selects `/usr/bin/ncdump` over the broken anaconda build
  and agrees with the portal. Backups:
  `/home/lzhenn/RUMI-code-backup-20260819-archive-experiment-fix.tar.gz` and
  `rumi_portal.sqlite3.backup-20260819-archive-experiment-fix`.

  Lesson worth keeping: mocking the expensive dependency in every test of a
  subsystem leaves the integration between them untested, and that is exactly
  where the metadata contract broke. At least one test per subsystem should run
  the real thing.
