#!/usr/bin/env python3
"""Test fixture generator for RUMI v3 submission archives.

Builds a directory tree (and, optionally, a packaged ``.tar.gz``/``.tgz``/
``.zip`` archive) that mimics what a participant would upload:

    <INST>-<MODEL>-<EVENT>-<POC>[-CONFIG<NN>][-MEM<NN>]/
        Participant_Model_Documentation.pdf
        ERA5-AN/
            Init-0/
                ERA5-AN-<MODEL>-<EVENT>-<YYYYMMDDHHMMSS>.nc
        GFS-FC/
            Init-1/
                ...
            Init-0.25/
                ...

This module is meant to be reused by every Phase 2/3/4 test in this repo, as
a CLI (``python3 tests/fixtures/make_fixture_archive.py OUTDIR ...``) and as
an importable library (``from fixtures.make_fixture_archive import
make_fixture``).

Design notes
------------
- Importing this module has no side effects beyond inserting
  ``portal/backend`` onto ``sys.path`` (needed to reach ``rumi_protocol``,
  the single source of truth for the RUMI event calendar / naming rules).
  Nothing is written to disk until ``make_fixture()`` (or ``main()``) is
  called.
- The default code path (``--real-netcdf`` not given) never imports
  ``netCDF4``/``numpy``: NetCDF files are replaced with small deterministic
  placeholder text files, so unit tests that only care about archive/file
  *structure* do not need the netCDF4 package installed. ``netCDF4`` and
  ``numpy`` are imported lazily, only inside the ``--real-netcdf`` code
  path.
- Corruption/truncation options (``--hours``, ``--gap``, ``--drop-first``,
  ``--drop-last``, ``--duplicate``) are applied, per tree, in that exact
  order to the tree's timestamp list:
    1. ``--hours N`` truncates to the first ``N - 1`` timestamps plus the
       final required timestamp (so end-of-period coverage still holds,
       unless a later step removes it again).
    2. ``--gap N`` deletes the timestamp currently at index ``N`` (0-based).
    3. ``--drop-first`` deletes whatever is currently first.
    4. ``--drop-last`` deletes whatever is currently last.
    5. ``--duplicate`` duplicates whatever timestamp is currently last into
       a second file with a ``_dup`` filename suffix (same timestamp).
"""

import argparse
import datetime as dt
import json
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "portal" / "backend"))

import rumi_protocol  # noqa: E402


DEFAULT_TREE = "ERA5-AN/Init-0"

ARCHIVE_EXTENSIONS = {
    "none": "tar.gz",  # canonical name used for `archive_name` even if unpacked
    "tar.gz": "tar.gz",
    "tgz": "tgz",
    "zip": "zip",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _actual_init_for(event: str, init_label: str) -> Optional[str]:
    """Resolve an ``Init-*`` label to an authoritative ISO timestamp.

    Mirrors the three cases described by the RUMI v3 protocol:
    - ``Init-5`` .. ``Init-0.25``: looked up via ``rumi_protocol.init_time_for``.
    - ``Init-0``: returns ``None`` (participant-defined single AN init).
    - ``Init-<YYYYMMDDHH>`` (absolute label): parsed directly.
    - Anything else (unknown/malformed label): returns ``None``, same as
      ``Init-0``, so intentionally-bogus init labels can still be used to
      build fixtures that test rejection of bad directory names.
    """
    absolute = rumi_protocol.parse_absolute_init_label(init_label)
    if absolute is not None:
        return absolute
    return rumi_protocol.init_time_for(event, init_label)


def _nc_filename(experiment: str, model: str, event: str, ts_iso: str) -> str:
    moment = rumi_protocol.parse_utc(ts_iso)
    stamp = moment.strftime("%Y%m%d%H%M%S")
    return f"{experiment}-{model}-{event}-{stamp}.nc"


def _lead_hours(ts_iso: str, init_iso: str) -> int:
    delta = rumi_protocol.parse_utc(ts_iso) - rumi_protocol.parse_utc(init_iso)
    return int(round(delta.total_seconds() / 3600.0))


def _global_attrs(
    *,
    experiment: str,
    event: str,
    institution: str,
    model: str,
    config: str,
    version: str,
    simulation_start_time: str,
    initialization_time: str,
    forecast_lead_time_hours: int,
    horizontal_resolution: str,
    creation_date: str,
) -> Dict[str, str]:
    """Build a placeholder value for every REQUIRED_GLOBAL_ATTRS / PHYSICS_ATTRS
    global attribute, per the values dictated by the tree/event/options."""
    event_name = rumi_protocol.EVENTS[event]["name"]
    forcing_mode = "analysis" if experiment.endswith("-AN") else "forecast"
    parts = experiment.split("-")
    forcing_source = parts[1] if len(parts) > 1 else experiment

    attrs = {
        "Conventions": "CF-1.8",
        "title": f"RUMI {experiment} fixture output: {event_name}",
        "institution": institution,
        "source": model,
        "history": f"Created {creation_date} by tests/fixtures/make_fixture_archive.py",
        "experiment": experiment,
        "event": event,
        "event_name": event_name,
        "simulation_start_time": simulation_start_time,
        "initialization_time": initialization_time,
        "forecast_initialization_time": initialization_time,
        "forecast_lead_time_hours": str(forecast_lead_time_hours),
        "forcing_mode": forcing_mode,
        "forcing_source": forcing_source,
        "forcing_data": (
            f"{forcing_source} "
            + ("reanalysis data" if forcing_mode == "analysis" else "forecast data")
        ),
        "forcing_data_version": "v1",
        "forcing_resolution": "0.25 degree",
        "forcing_update_interval": "1 hour" if forcing_mode == "analysis" else "6 hour",
        "horizontal_resolution": horizontal_resolution,
        "contact": "fixture@example.org",
        "creator_name": "RUMI Fixture Generator",
        "creation_date": creation_date,
        "version": f"r{version}",
        # Extra convenience attrs (not in REQUIRED_GLOBAL_ATTRS, harmless).
        "model": model,
        "config": config,
    }
    for name in rumi_protocol.PHYSICS_ATTRS:
        attrs[name] = f"fixture-placeholder-{name}"
    return attrs


def _write_placeholder_netcdf(path: Path, attrs: Dict[str, str]) -> None:
    """Write a small deterministic stand-in for a NetCDF file.

    Not a real NetCDF4 file -- just enough content (including the would-be
    global attributes) to be useful when eyeballing a fixture on disk. Kept
    out of the archive's directory *structure* concerns: only the file name
    and location matter for structure-focused tests.
    """
    lines = ["RUMI fixture placeholder (not a real NetCDF file)", ""]
    for key in sorted(attrs):
        lines.append(f"{key}={attrs[key]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_real_netcdf(path: Path, attrs: Dict[str, str], ts_iso: str) -> None:
    """Write a real NetCDF4 file satisfying the full RUMI variable
    checklist: the core grid, the nine core 2D variables, the five
    recommended radiation 2D variables, the six recommended 3D variables,
    and OMEGA (which, together with W, satisfies the OMEGA|W alternative) on
    the three standard pressure levels.

    All data is a small deterministic constant per variable (index-based),
    not random, so fixtures stay reproducible and small. Imports
    ``netCDF4``/``numpy`` locally so the rest of this module (and every
    non-``--real-netcdf`` fixture) stays free of that dependency.
    """
    import netCDF4 as nc
    import numpy as np

    grid = rumi_protocol.CORE_GRID
    nlat, nlon = grid["nlat"], grid["nlon"]
    lat_values = np.array(
        [grid["lat_south"] + i * grid["resolution_degrees"] for i in range(nlat)],
        dtype="f8",
    )
    lon_values = np.array(
        [grid["lon_west"] + j * grid["resolution_degrees"] for j in range(nlon)],
        dtype="f8",
    )
    pressure_values = np.array(
        [level * 100 for level in rumi_protocol.RECOMMENDED_3D_LEVELS_HPA], dtype="f4"
    )
    npres = len(pressure_values)

    moment = rumi_protocol.parse_utc(ts_iso)
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    time_seconds = (moment - epoch).total_seconds()

    with nc.Dataset(str(path), mode="w", format="NETCDF4") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("lat", nlat)
        ds.createDimension("lon", nlon)
        ds.createDimension("pressure", npres)

        tvar = ds.createVariable("time", "f8", ("time",))
        tvar.long_name = "time"
        tvar.standard_name = "time"
        tvar.units = "seconds since 1970-01-01 00:00:00"
        tvar.calendar = "gregorian"
        tvar.axis = "T"
        tvar[:] = [time_seconds]

        latvar = ds.createVariable("lat", "f8", ("lat",))
        latvar.long_name = "latitude"
        latvar.standard_name = "latitude"
        latvar.units = "degrees_north"
        latvar.axis = "Y"
        latvar[:] = lat_values

        lonvar = ds.createVariable("lon", "f8", ("lon",))
        lonvar.long_name = "longitude"
        lonvar.standard_name = "longitude"
        lonvar.units = "degrees_east"
        lonvar.axis = "X"
        lonvar[:] = lon_values

        pvar = ds.createVariable("pressure", "f4", ("pressure",))
        pvar.long_name = "pressure"
        pvar.standard_name = "air_pressure"
        pvar.units = "Pa"
        pvar.positive = "down"
        pvar.axis = "Z"
        pvar[:] = pressure_values

        two_d_vars = list(rumi_protocol.CORE_2D_VARS) + list(
            rumi_protocol.RECOMMENDED_RADIATION_VARS
        )
        for index, name in enumerate(two_d_vars):
            var = ds.createVariable(
                name,
                "f4",
                ("time", "lat", "lon"),
                fill_value=np.float32(-9999.0),
                zlib=True,
            )
            var.long_name = name
            var.units = "1"
            var.coordinates = "lat lon"
            var[:] = np.full((1, nlat, nlon), float(index + 1), dtype="f4")

        # RECOMMENDED_3D_LEVEL_VARS (T, Z, RH, U, V, Q) plus OMEGA, which
        # satisfies the OMEGA|W recommended vertical-velocity alternative.
        three_d_vars = list(rumi_protocol.RECOMMENDED_3D_LEVEL_VARS) + ["OMEGA"]
        for index, name in enumerate(three_d_vars):
            var = ds.createVariable(
                name,
                "f4",
                ("time", "pressure", "lat", "lon"),
                fill_value=np.float32(-9999.0),
                zlib=True,
            )
            var.long_name = name
            var.units = "1"
            var.coordinates = "lat lon pressure"
            var[:] = np.full((1, npres, nlat, nlon), float(index + 1), dtype="f4")

        for key, value in attrs.items():
            setattr(ds, key, value)


def _write_netcdf_file(
    path: Path, attrs: Dict[str, str], ts_iso: str, real_netcdf: bool
) -> None:
    if real_netcdf:
        _write_real_netcdf(path, attrs, ts_iso)
    else:
        _write_placeholder_netcdf(path, attrs)


def _write_meta(meta_path: Path, result: Dict) -> None:
    payload = {
        "stem": result["stem"],
        "archive_name": result["archive_name"],
        "root": str(result["root"]),
        "archive": str(result["archive"]) if result["archive"] else None,
        "doc": str(result["doc"]) if result["doc"] else None,
        "trees": result["trees"],
        "options": result["options"],
    }
    meta_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_fixture(
    outdir,
    *,
    institution: str = "HKUST",
    model: str = "MPAS",
    event: str = "HRAIN2025",
    poc: str = "LIU",
    config: str = "CONFIG01",
    version: str = "01",
    tree: Optional[List[str]] = None,
    resolution: str = "1 km",
    hours: Optional[int] = None,
    drop_last: bool = False,
    drop_first: bool = False,
    gap: Optional[int] = None,
    duplicate: bool = False,
    no_doc: bool = False,
    bad_init_time: bool = False,
    skew_init_hours: int = 0,
    real_netcdf: bool = False,
    archive: str = "none",
) -> Dict:
    """Build a RUMI v3 fixture archive under ``outdir``.

    Parameters mirror the CLI options 1:1 (see module docstring / ``--help``
    for the corruption-option application order). Returns::

        {
            "root": Path,             # OUTDIR/<stem>/  (always created)
            "archive": Path | None,   # OUTDIR/<stem>.<ext>, or None if
                                       # archive == "none"
            "stem": str,               # "<INST>-<MODEL>-<EVENT>-<POC>-<CONFIG>"
            "archive_name": str,       # stem + canonical extension
            "doc": Path | None,        # Participant_Model_Documentation.pdf, or None
            "meta_path": Path,         # OUTDIR/_fixture_meta.json
            "trees": {
                "GFS-FC/Init-1": {
                    "experiment": str,
                    "init_label": str,
                    "category": "km" | "subkm",
                    "init": str,            # effective (unperturbed) init, ISO
                    "written_init": str,    # init actually written to file attrs
                                             # (may differ under --bad-init-time /
                                             # --skew-init-hours)
                    "timestamps": [str, ...],   # ISO timestamps actually written
                    "files": [str, ...],        # file names, sorted
                    "dropped": [str, ...],      # ISO timestamps intentionally
                                                 # left out (hours/gap/drop-*)
                    "duplicated_file": str | None,
                },
                ...
            },
            "options": {...},          # every keyword argument, as given/defaulted
        }
    """
    if archive not in ARCHIVE_EXTENSIONS:
        raise ValueError(f"Unknown --archive format: {archive!r}")
    if bad_init_time and skew_init_hours:
        raise ValueError(
            "--bad-init-time and --skew-init-hours are mutually exclusive"
        )
    if hours is not None and hours < 1:
        raise ValueError("--hours must be >= 1")
    if event not in rumi_protocol.EVENTS:
        raise ValueError(f"Unknown event: {event!r}")

    trees = list(tree) if tree else [DEFAULT_TREE]

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    stem = f"{institution}-{model}-{event}-{poc}-{config}"
    root = outdir / stem
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    doc_path = None
    if not no_doc:
        doc_path = root / "Participant_Model_Documentation.pdf"
        doc_path.write_bytes(
            b"%PDF-1.4\n% RUMI fixture placeholder documentation.\n%%EOF\n"
        )

    creation_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    tree_meta = {}
    for entry in trees:
        if "/" not in entry:
            raise ValueError(f"--tree must be EXPERIMENT/INIT, got {entry!r}")
        experiment, init_label = entry.split("/", 1)

        category = rumi_protocol.resolution_category(resolution) or "km"
        period = rumi_protocol.required_period(event, category)
        if period is None:
            raise ValueError(
                f"No required period for event={event!r} category={category!r}"
            )

        actual_init = _actual_init_for(event, init_label)
        effective_init = actual_init if actual_init is not None else period[0]

        timestamps = rumi_protocol.expected_timestamps(event, category, actual_init)
        if not timestamps:
            raise ValueError(
                f"No expected timestamps for tree {entry!r} "
                f"(event={event!r}, category={category!r}, actual_init={actual_init!r})"
            )

        # --- corruption / truncation options, applied in documented order ---
        working = list(timestamps)
        if hours is not None and hours < len(working):
            working = working[: hours - 1] + [working[-1]]
        if gap is not None:
            if not (0 <= gap < len(working)):
                raise ValueError(
                    f"--gap {gap} out of range for tree {entry!r} "
                    f"(sequence currently has {len(working)} timestamps)"
                )
            del working[gap]
        if drop_first and working:
            working = working[1:]
        if drop_last and working:
            working = working[:-1]

        # --- init-time attribute perturbation ---
        written_init = effective_init
        if bad_init_time:
            written_init = rumi_protocol.iso_z(
                rumi_protocol.parse_utc(effective_init) + dt.timedelta(hours=30)
            )
        elif skew_init_hours:
            written_init = rumi_protocol.iso_z(
                rumi_protocol.parse_utc(effective_init)
                + dt.timedelta(hours=skew_init_hours)
            )

        init_dir = root / experiment / init_label
        init_dir.mkdir(parents=True, exist_ok=True)

        file_names = []
        for ts in working:
            fname = _nc_filename(experiment, model, event, ts)
            lead_hours = _lead_hours(ts, effective_init)
            attrs = _global_attrs(
                experiment=experiment,
                event=event,
                institution=institution,
                model=model,
                config=config,
                version=version,
                simulation_start_time=effective_init,
                initialization_time=written_init,
                forecast_lead_time_hours=lead_hours,
                horizontal_resolution=resolution,
                creation_date=creation_date,
            )
            _write_netcdf_file(init_dir / fname, attrs, ts, real_netcdf)
            file_names.append(fname)

        duplicated_name = None
        if duplicate and working:
            last_ts = working[-1]
            base = _nc_filename(experiment, model, event, last_ts)
            dup_name = base[:-3] + "_dup.nc"
            lead_hours = _lead_hours(last_ts, effective_init)
            attrs = _global_attrs(
                experiment=experiment,
                event=event,
                institution=institution,
                model=model,
                config=config,
                version=version,
                simulation_start_time=effective_init,
                initialization_time=written_init,
                forecast_lead_time_hours=lead_hours,
                horizontal_resolution=resolution,
                creation_date=creation_date,
            )
            _write_netcdf_file(init_dir / dup_name, attrs, last_ts, real_netcdf)
            file_names.append(dup_name)
            duplicated_name = dup_name

        tree_meta[entry] = {
            "experiment": experiment,
            "init_label": init_label,
            "category": category,
            "init": effective_init,
            "written_init": written_init,
            "timestamps": working,
            "files": sorted(file_names),
            "dropped": sorted(set(timestamps) - set(working)),
            "duplicated_file": duplicated_name,
        }

    archive_name = f"{stem}.{ARCHIVE_EXTENSIONS[archive]}"

    archive_path = None
    if archive != "none":
        archive_path = outdir / archive_name
        if archive_path.exists():
            archive_path.unlink()
        if archive == "zip":
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in sorted(root.rglob("*")):
                    if file_path.is_file():
                        rel_parts = (stem,) + file_path.relative_to(root).parts
                        zf.write(file_path, arcname="/".join(rel_parts))
        else:  # "tar.gz" / "tgz" both use gzip-compressed tar
            with tarfile.open(archive_path, "w:gz") as tf:
                tf.add(root, arcname=stem)

    result = {
        "root": root,
        "archive": archive_path,
        "stem": stem,
        "archive_name": archive_name,
        "doc": doc_path,
        "trees": tree_meta,
        "options": {
            "institution": institution,
            "model": model,
            "event": event,
            "poc": poc,
            "config": config,
            "version": version,
            "tree": trees,
            "resolution": resolution,
            "hours": hours,
            "drop_last": drop_last,
            "drop_first": drop_first,
            "gap": gap,
            "duplicate": duplicate,
            "no_doc": no_doc,
            "bad_init_time": bad_init_time,
            "skew_init_hours": skew_init_hours,
            "real_netcdf": real_netcdf,
            "archive": archive,
        },
    }

    meta_path = outdir / "_fixture_meta.json"
    _write_meta(meta_path, result)
    result["meta_path"] = meta_path

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a RUMI v3 submission-archive test fixture."
    )
    parser.add_argument("outdir", help="Directory to write the fixture into.")
    parser.add_argument("--institution", default="HKUST")
    parser.add_argument("--model", default="MPAS")
    parser.add_argument("--event", default="HRAIN2025")
    parser.add_argument("--poc", default="LIU")
    parser.add_argument("--config", default="CONFIG01")
    parser.add_argument("--version", default="01")
    parser.add_argument(
        "--tree",
        action="append",
        metavar="EXPERIMENT/INIT",
        help=f"Repeatable. Defaults to a single {DEFAULT_TREE!r} tree.",
    )
    parser.add_argument("--resolution", default="1 km")
    parser.add_argument("--hours", type=int, default=None)
    parser.add_argument("--drop-last", action="store_true")
    parser.add_argument("--drop-first", action="store_true")
    parser.add_argument("--gap", type=int, default=None)
    parser.add_argument("--duplicate", action="store_true")
    parser.add_argument("--no-doc", action="store_true")
    parser.add_argument("--bad-init-time", action="store_true")
    parser.add_argument("--skew-init-hours", type=int, default=0)
    parser.add_argument("--real-netcdf", action="store_true")
    parser.add_argument(
        "--archive", choices=["none", "tar.gz", "tgz", "zip"], default="none"
    )
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    result = make_fixture(
        args.outdir,
        institution=args.institution,
        model=args.model,
        event=args.event,
        poc=args.poc,
        config=args.config,
        version=args.version,
        tree=args.tree,
        resolution=args.resolution,
        hours=args.hours,
        drop_last=args.drop_last,
        drop_first=args.drop_first,
        gap=args.gap,
        duplicate=args.duplicate,
        no_doc=args.no_doc,
        bad_init_time=args.bad_init_time,
        skew_init_hours=args.skew_init_hours,
        real_netcdf=args.real_netcdf,
        archive=args.archive,
    )
    target = result["archive"] or result["root"]
    print(str(target.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
