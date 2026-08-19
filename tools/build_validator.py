#!/usr/bin/env python3
"""Generate ``portal/downloads/rumi_validate.py`` from ``rumi_protocol.py``.

``portal/backend/rumi_protocol.py`` is the single source of truth for the
RUMI submission validation rules. The block between its
``# --- BEGIN INLINE ---`` and ``# --- END INLINE ---`` markers is extracted
*verbatim* by this script and spliced into a small CLI template to produce
``portal/downloads/rumi_validate.py``: a single, dependency-light file that
participants download and run on their own machines to get exactly the same
verdict the portal would give them.

No validation rule is re-implemented here or in the CLI template -- this
script only does text extraction and string concatenation, and the CLI
template only reads files and formats a report, calling the inlined
functions to make every judgement call.

Usage:
    python3 tools/build_validator.py            # (re)generate the file
    python3 tools/build_validator.py --check     # verify it is up to date;
                                                  # exit 1 (no write) if not

Regeneration is fully deterministic given the same ``rumi_protocol.py``
content (no timestamps or other non-reproducible values are embedded), so
``--check`` can be used as a CI/test guard against editing the rules without
rebuilding the downloadable validator.
"""

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "portal" / "backend" / "rumi_protocol.py"
OUTPUT_PATH = ROOT / "portal" / "downloads" / "rumi_validate.py"

BEGIN_MARKER = "# --- BEGIN INLINE ---"
END_MARKER = "# --- END INLINE ---"


def extract_inline_block(protocol_source):
    """Return the text between the BEGIN/END INLINE markers, verbatim.

    The marker lines themselves are excluded; everything in between --
    docstring, imports, constants, and every rule function -- is returned
    unmodified. This is the entire rule surface participants are judged
    against, and it is never rewritten or summarized here.
    """
    lines = protocol_source.splitlines()
    begin = None
    end = None
    for index, line in enumerate(lines):
        if line.strip() == BEGIN_MARKER and begin is None:
            begin = index
        elif line.strip() == END_MARKER and end is None:
            end = index
    if begin is None or end is None:
        raise SystemExit(
            f"{PROTOCOL_PATH}: could not find both "
            f"{BEGIN_MARKER!r} and {END_MARKER!r} marker lines"
        )
    if end <= begin:
        raise SystemExit(
            f"{PROTOCOL_PATH}: {END_MARKER!r} appears before {BEGIN_MARKER!r}"
        )
    inline_lines = lines[begin + 1 : end]
    return "\n".join(inline_lines).strip("\n")


MODULE_DOCSTRING = '''"""RUMI v3 submission local validator.

*** THIS FILE IS AUTO-GENERATED. DO NOT EDIT IT BY HAND. ***

It is built by ``tools/build_validator.py`` from the single source of truth
for the validation rules, ``portal/backend/rumi_protocol.py`` (the block
between that file's ``# --- BEGIN INLINE ---`` / ``# --- END INLINE ---``
markers is inlined verbatim below, unchanged). To change any validation
rule, edit ``rumi_protocol.py`` and regenerate this file with::

    python3 tools/build_validator.py

then commit the regenerated file alongside the rule change.

This script is downloaded and run standalone by RUMI participants on their
own machines, so it depends only on the Python standard library plus one
*optional* third-party package, ``netCDF4``. When ``netCDF4`` is not
installed, it falls back to shelling out to the ``ncdump`` command-line tool
(commonly available from a NetCDF or Conda install). If neither is
available, only the archive/file-name structure can be checked, and the
report says so plainly instead of guessing.

Usage:
    python3 rumi_validate.py SUBMISSION_DIR/
    python3 rumi_validate.py SUBMISSION_ARCHIVE.tar.gz
    python3 rumi_validate.py --write-manifest SUBMISSION_DIR/
    python3 rumi_validate.py --json SUBMISSION_DIR/
    python3 rumi_validate.py --quiet SUBMISSION_DIR/
    python3 rumi_validate.py --reader ncdump SUBMISSION_DIR/

Exit codes:
    0  validation passed (there may still be warnings)
    1  validation failed (at least one error)
    2  the tool could not run at all: the path does not exist, or no
       NetCDF reader (netCDF4 package or ncdump command) is available and
       one was needed
"""'''


CLI_IMPORTS = """
import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

try:
    import netCDF4  # type: ignore
except Exception:  # pragma: no cover - exercised only without the package
    netCDF4 = None
""".strip(
    "\n"
)


CLI_CODE = '''
# ---------------------------------------------------------------------------
# CLI: reads files (directory tree or .tar.gz/.tgz/.zip archive) and NetCDF
# metadata (via netCDF4 or ncdump), then formats a report. Every pass/fail
# judgement below is delegated to the inlined functions above -- this
# section never decides on its own whether a submission is valid.
# ---------------------------------------------------------------------------

VALIDATOR_VERSION = "1.0.0"

MANIFEST_NAME = "rumi_manifest.json"
PROGRESS_INTERVAL = 25

# Maps netCDF4's Dataset.data_model strings to the equivalent `ncdump -k`
# output, so validate_netcdf_facts()'s "netCDF-4" substring check behaves
# identically regardless of which reader produced the facts.
KIND_MAP = {
    "NETCDF4": "netCDF-4",
    "NETCDF4_CLASSIC": "netCDF-4 classic model",
    "NETCDF3_CLASSIC": "classic",
    "NETCDF3_64BIT": "64-bit offset",
    "NETCDF3_64BIT_OFFSET": "64-bit offset",
    "NETCDF3_64BIT_DATA": "64-bit data",
}


class ReaderUnavailable(Exception):
    """Raised when the requested NetCDF reader cannot be used."""


# --- Archive/directory member access ---------------------------------------


class _TarSource:
    def __init__(self, path):
        self._tar = tarfile.open(str(path), "r:*")
        self._members = {m.name: m for m in self._tar.getmembers() if m.isfile()}

    def names(self):
        return list(self._members.keys())

    def extract_to(self, name, dest):
        member = self._members[name]
        source = self._tar.extractfile(member)
        if source is None:
            raise OSError(f"could not read archive member: {name}")
        with source, open(dest, "wb") as out:
            shutil.copyfileobj(source, out, length=1024 * 1024)

    def close(self):
        self._tar.close()


class _ZipSource:
    def __init__(self, path):
        self._zip = zipfile.ZipFile(str(path))
        self._members = {i.filename: i for i in self._zip.infolist() if not i.is_dir()}

    def names(self):
        return list(self._members.keys())

    def extract_to(self, name, dest):
        with self._zip.open(self._members[name]) as source, open(dest, "wb") as out:
            shutil.copyfileobj(source, out, length=1024 * 1024)

    def close(self):
        self._zip.close()


def _open_archive_source(path):
    lower = str(path).lower()
    if lower.endswith(".zip"):
        return _ZipSource(path)
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        return _TarSource(path)
    raise ValueError(f"unsupported archive type: {path}")


def _resolve_target(target_path):
    """Return (kind, names, archive_name, local_path, cleanup).

    ``names`` are archive-relative member paths, always prefixed with the
    top-level directory/stem name, exactly as they would appear inside a
    packaged ``.tar.gz`` -- this lets a plain extracted directory be judged
    by the very same ``validate_archive_structure()`` the portal runs on an
    uploaded archive. ``local_path(name)`` is a context manager yielding a
    real filesystem ``Path`` for that member (for an archive, a temporary
    extracted copy that is removed when the ``with`` block exits).
    """
    if target_path.is_dir():
        stem = target_path.name
        names = []
        local_paths = {}
        for path in sorted(target_path.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(target_path).as_posix()
            if rel == MANIFEST_NAME:
                # Exclude our own previous output so re-running the
                # validator (e.g. --write-manifest twice) stays idempotent.
                continue
            name = f"{stem}/{rel}"
            names.append(name)
            local_paths[name] = path
        names.sort()

        @contextlib.contextmanager
        def local_path(name):
            yield local_paths[name]

        return "directory", names, f"{stem}.tar.gz", local_path, (lambda: None)

    lower = str(target_path).lower()
    if target_path.is_file() and lower.endswith((".tar.gz", ".tgz", ".zip")):
        source = _open_archive_source(target_path)
        names = sorted(source.names())

        @contextlib.contextmanager
        def local_path(name):
            with tempfile.TemporaryDirectory(prefix="rumi-validate-") as tmp:
                dest = Path(tmp) / "member.nc"
                source.extract_to(name, dest)
                yield dest

        return "archive", names, target_path.name, local_path, source.close

    return None, [], "", None, (lambda: None)


# --- NetCDF readers ----------------------------------------------------------


def _facts_via_netcdf4(path):
    ds = netCDF4.Dataset(str(path))
    try:
        attr_names = set(ds.ncattrs())
        attributes = {}
        for name in KNOWN_ATTRIBUTES:
            if name in attr_names:
                value = ds.getncattr(name)
                attributes[name] = None if value is None else str(value)
            else:
                attributes[name] = None
        variables = sorted(name for name in ALL_KNOWN_VARS if name in ds.variables)
        dimensions = {
            "lat": len(ds.dimensions["lat"]) if "lat" in ds.dimensions else None,
            "lon": len(ds.dimensions["lon"]) if "lon" in ds.dimensions else None,
        }
        lat = [float(v) for v in ds.variables["lat"][:]] if "lat" in ds.variables else []
        lon = [float(v) for v in ds.variables["lon"][:]] if "lon" in ds.variables else []
        kind = KIND_MAP.get(ds.data_model, ds.data_model)
    finally:
        ds.close()
    return {
        "kind": kind,
        "attributes": attributes,
        "variables": variables,
        "dimensions": dimensions,
        "lat": lat,
        "lon": lon,
    }


def _find_ncdump():
    candidate = os.environ.get("RUMI_NCDUMP")
    if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return shutil.which("ncdump")


def _run_ncdump(ncdump_exe, args, timeout=90):
    return subprocess.run(
        [ncdump_exe] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


def _ncdump_coordinates(ncdump_exe, path):
    proc = _run_ncdump(ncdump_exe, ["-p", "15,15", "-v", "lat,lon", str(path)])
    if proc.returncode != 0:
        raise OSError(f"ncdump could not read coordinates: {proc.stderr.strip()}")
    sections = proc.stdout.split("data:", 1)
    if len(sections) != 2:
        return {"lat": [], "lon": []}

    def values(name):
        match = re.search(
            r"(?:^|\\n)\\s*" + re.escape(name) + r"\\s*=\\s*(.*?);",
            sections[1],
            flags=re.DOTALL,
        )
        if not match:
            return []
        return [
            float(value)
            for value in re.findall(
                r"[-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[Ee][-+]?\\d+)?",
                match.group(1),
            )
        ]

    return {"lat": values("lat"), "lon": values("lon")}


def _facts_via_ncdump(ncdump_exe, path):
    kind_proc = _run_ncdump(ncdump_exe, ["-k", str(path)], timeout=30)
    if kind_proc.returncode != 0:
        raise OSError(f"ncdump -k failed: {kind_proc.stderr.strip()}")
    header_proc = _run_ncdump(ncdump_exe, ["-h", str(path)], timeout=90)
    if header_proc.returncode != 0:
        raise OSError(f"ncdump -h failed: {header_proc.stderr.strip()}")
    coordinates = _ncdump_coordinates(ncdump_exe, path)
    return netcdf_facts_from_header(kind_proc.stdout.strip(), header_proc.stdout, coordinates)


def _resolve_reader(choice):
    """Return (reader_name, read_fn(path) -> facts dict), or raise ReaderUnavailable."""
    if choice in ("auto", "netcdf4") and netCDF4 is not None:
        return "netcdf4", _facts_via_netcdf4
    ncdump_exe = _find_ncdump()
    if choice in ("auto", "ncdump") and ncdump_exe:
        return "ncdump", (lambda path: _facts_via_ncdump(ncdump_exe, path))
    if choice == "netcdf4":
        raise ReaderUnavailable(
            "the netCDF4 Python package is not installed. Install it with "
            "'pip install netCDF4', or rerun with --reader ncdump."
        )
    if choice == "ncdump":
        raise ReaderUnavailable(
            "the ncdump command was not found on PATH (set RUMI_NCDUMP to "
            "its full path, or rerun with --reader netcdf4)."
        )
    raise ReaderUnavailable(
        "no NetCDF reader is available: install the netCDF4 Python package "
        "('pip install netCDF4') or make sure the ncdump command is on PATH."
    )


# --- Small helpers -----------------------------------------------------------


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utcnow_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


# --- Reporting ---------------------------------------------------------------


def _emit(args, target_path, reader_name, errors, warnings, coverage_by_key):
    passed = not errors

    if args.json:
        payload = {
            "rules_version": RULES_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "reader": reader_name,
            "target": str(target_path),
            "result": "pass" if passed else "fail",
            "errors": errors,
            "warnings": warnings,
            "coverage": coverage_by_key,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if passed else 1

    print(f"RESULT: {'PASS' if passed else 'FAIL'} ({len(errors)} errors, {len(warnings)} warnings)")
    if passed and target_path.is_dir():
        # Validating the extracted folder cannot see the name you will give the
        # archive, and the portal checks that name. Spell out the exact command
        # so the two cannot disagree.
        stem = target_path.name
        print()
        print("Next step - pack it with exactly this name:")
        print(f"  tar -czf {stem}.tar.gz {stem}/")
    if args.quiet:
        return 0 if passed else 1

    print()
    print(f"ERRORS ({len(errors)}):")
    if errors:
        for message in errors:
            print(f"  - {message}")
    else:
        print("  (none)")
    print()
    print(f"WARNINGS ({len(warnings)}):")
    if warnings:
        for message in warnings:
            print(f"  - {message}")
    else:
        print("  (none)")

    if coverage_by_key:
        print()
        print("COVERAGE:")
        print(
            f"  {'experiment/init':<40}{'files':>7}{'required':>10}"
            f"{'start':>22}{'end':>22}{'missing':>9}{'category':>10}"
        )
        for key in sorted(coverage_by_key):
            cov = coverage_by_key[key]
            start = cov.get("required_start") or cov.get("first") or "-"
            end = cov.get("required_end") or cov.get("last") or "-"
            category = cov.get("category") or "-"
            print(
                f"  {key:<40}{cov.get('files', 0):>7}{cov.get('expected', 0):>10}"
                f"{start:>22}{end:>22}{cov.get('missing', 0):>9}{category:>10}"
            )

    return 0 if passed else 1


# --- Main flow ----------------------------------------------------------------


def run(args):
    target_path = Path(args.path).expanduser()
    if not target_path.exists():
        print(f"error: path does not exist: {target_path}", file=sys.stderr)
        return 2

    kind, names, archive_name, local_path, cleanup = _resolve_target(target_path)
    if kind is None:
        print(
            f"error: {target_path} is neither a directory nor a "
            f".tar.gz/.tgz/.zip archive.",
            file=sys.stderr,
        )
        return 2

    try:
        reader_name = None
        read_fn = None
        reader_error = None
        try:
            reader_name, read_fn = _resolve_reader(args.reader)
        except ReaderUnavailable as exc:
            reader_error = str(exc)

        if not args.quiet and not args.json:
            print(
                f"RUMI local validator {VALIDATOR_VERSION} "
                f"(rules_version={RULES_VERSION}, reader={reader_name or 'unavailable'})"
            )
            print(f"target: {target_path} ({kind})")

        errors = IssueLog()
        warnings = IssueLog()

        structure = validate_archive_structure(names, archive_name)
        for message in structure["errors"]:
            errors.add(message)
        for message in structure["warnings"]:
            warnings.add(message)
        layout = structure["layout"]

        if errors:
            # Structure is broken: report it and stop. No NetCDF file is
            # opened, matching the portal's own behavior (see
            # validate_archive()'s "Per-file checks were skipped" path).
            return _emit(args, target_path, reader_name, errors.messages(), warnings.messages(), {})

        if layout and read_fn is None:
            print(f"error: {reader_error or 'no NetCDF reader is available.'}", file=sys.stderr)
            return 2

        members_by_directory = {}
        sha256_by_group = {}
        total = len(layout)
        done = 0
        for name, placement in sorted(layout.items()):
            with local_path(name) as file_path:
                try:
                    facts = read_fn(file_path) if read_fn else None
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                    errors.add(f"NetCDF file could not be read: {exc}", name)
                    facts = None
                if args.write_manifest:
                    try:
                        group = (placement["experiment"], placement["init"])
                        sha256_by_group.setdefault(group, {})[placement["file_name"]] = (
                            _sha256_file(file_path)
                        )
                    except OSError as exc:
                        errors.add(f"Could not hash file for manifest: {exc}", name)

            verdict = validate_netcdf_facts(placement["file_name"], facts, {})
            for message in verdict["errors"]:
                errors.add(message, name)
            for message in verdict["warnings"]:
                warnings.add(message, name)

            key = (placement["experiment"], placement["init"])
            members_by_directory.setdefault(key, []).append(
                {
                    "name": name,
                    "timestamp": placement["timestamp"],
                    "time_metadata": verdict["summary"].get("time_metadata") or {},
                }
            )

            done += 1
            if (
                not args.quiet
                and not args.json
                and total
                and (done % PROGRESS_INTERVAL == 0 or done == total)
            ):
                print(f"checked {done}/{total}")

        event = (structure["summary"].get("archive") or {}).get("event")
        coverage_by_key = {}
        experiments_for_manifest = {}
        for (experiment, init_label), members in sorted(members_by_directory.items()):
            directory = validate_init_directory(event, experiment, init_label, members)
            for message in directory["errors"]:
                errors.add(message)
            for message in directory["warnings"]:
                warnings.add(message)
            coverage_by_key[f"{experiment}/{init_label}"] = directory["coverage"]
            if args.write_manifest:
                experiments_for_manifest.setdefault(experiment, {})[init_label] = {
                    "files": directory["coverage"]["files"],
                    "first": directory["coverage"]["first"],
                    "last": directory["coverage"]["last"],
                    "category": directory["coverage"]["category"],
                    "sha256": sha256_by_group.get((experiment, init_label), {}),
                }

        final_errors = errors.messages()
        final_warnings = warnings.messages()
        exit_code = _emit(args, target_path, reader_name, final_errors, final_warnings, coverage_by_key)

        if args.write_manifest and not final_errors:
            if kind != "directory":
                print(
                    "warning: --write-manifest requires a directory target "
                    "(extract the archive first); manifest not written.",
                    file=sys.stderr,
                )
            else:
                manifest = {
                    "rules_version": RULES_VERSION,
                    "validator_version": VALIDATOR_VERSION,
                    "generated_at": _utcnow_iso(),
                    "archive": {
                        k: v
                        for k, v in (structure["summary"].get("archive") or {}).items()
                        if k != "extension"
                    },
                    "participants": args.participants or "",
                    "experiments": experiments_for_manifest,
                }
                manifest_path = target_path / MANIFEST_NAME
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\\n", encoding="utf-8"
                )
                if not args.quiet and not args.json:
                    print(f"wrote {manifest_path}")

        return exit_code
    finally:
        cleanup()


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="rumi_validate.py",
        description=(
            "Validate a RUMI v3 submission (an extracted directory, or a "
            ".tar.gz/.tgz/.zip archive) against the same rules the portal "
            "uses, so problems can be found and fixed before uploading."
        ),
    )
    parser.add_argument(
        "path",
        help="Path to an extracted submission directory, or a .tar.gz/.tgz/.zip archive.",
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help=(
            "After a clean pass (no errors), write rumi_manifest.json inside "
            "the submission directory. Only valid for a directory target."
        ),
    )
    parser.add_argument(
        "--participants",
        default="",
        help="Comma-separated participant names to record in rumi_manifest.json.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print a machine-readable JSON report instead of text."
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Print only the final RESULT line."
    )
    parser.add_argument(
        "--reader",
        choices=["auto", "netcdf4", "ncdump"],
        default="auto",
        help=(
            "How to read NetCDF files: prefer the netCDF4 package, force "
            "ncdump, or auto-detect (default: auto, preferring netCDF4)."
        ),
    )
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    return run(args)
'''.strip(
    "\n"
)


def build_source():
    inline_block = extract_inline_block(PROTOCOL_PATH.read_text(encoding="utf-8"))
    parts = [
        "#!/usr/bin/env python3",
        MODULE_DOCSTRING,
        "",
        CLI_IMPORTS,
        "",
        "# " + "=" * 76,
        "# BEGIN inlined portal/backend/rumi_protocol.py rules (verbatim).",
        "# Do not edit this block by hand -- edit rumi_protocol.py and rerun",
        "# tools/build_validator.py.",
        "# " + "=" * 76,
        "",
        inline_block,
        "",
        "# " + "=" * 76,
        "# END inlined rules",
        "# " + "=" * 76,
        "",
        CLI_CODE,
        "",
        "",
        'if __name__ == "__main__":',
        "    sys.exit(main())",
        "",
    ]
    return "\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the generated file is up to date; do not write it.",
    )
    args = parser.parse_args(argv)

    generated = build_source()

    if args.check:
        if not OUTPUT_PATH.exists():
            print(
                f"{OUTPUT_PATH} does not exist; run tools/build_validator.py to create it.",
                file=sys.stderr,
            )
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if current != generated:
            print(
                f"{OUTPUT_PATH} is out of date; run tools/build_validator.py to regenerate.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH} is up to date.")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(generated, encoding="utf-8")
    OUTPUT_PATH.chmod(0o755)
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
