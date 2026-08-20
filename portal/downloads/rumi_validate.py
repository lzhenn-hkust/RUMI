#!/usr/bin/env python3
"""RUMI v3 submission local validator.

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
"""

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

# ============================================================================
# BEGIN inlined portal/backend/rumi_protocol.py rules (verbatim).
# Do not edit this block by hand -- edit rumi_protocol.py and rerun
# tools/build_validator.py.
# ============================================================================

"""Shared RUMI submission protocol rules (v3).

This module is the single source of truth for the RUMI event calendar,
required submission time coverage, initialization-time labels, experiment
directory names, archive/file naming patterns, and the core NetCDF grid
contract. It is imported by the portal backend (``portal_lib``) and is also
inlined verbatim (between the ``BEGIN INLINE`` / ``END INLINE`` markers
above/below) into the standalone ``rumi_validate.py`` local validator that
participants download and run on their own machines.

Constraints:
- Standard library only. Do not import numpy, netCDF4, or any portal
  backend module from this file.
- Must run unmodified on Python 3.10 (the deployment interpreter). Avoid
  3.11+ syntax such as ``Self``, ``ExceptionGroup``, or the new
  ``typing.TypeAlias`` statement form.
- Do not change the core grid definition or any other numerical constant
  copied from ``portal_lib.py``.
"""

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


RULES_VERSION = "2026-08-rumi-v3.1"
OUTPUT_INTERVAL_HOURS = 1

# ---------------------------------------------------------------------------
# Event calendar
# ---------------------------------------------------------------------------
# ``start``/``end`` are kept as aliases of ``baseline_start``/``baseline_end``
# for backward compatibility: ``portal_lib.validate_timestamp_in_event()``
# and the front-end ``app.js`` both read those two keys directly.

EVENTS: Dict[str, Dict[str, str]] = {
    "MANGKHUT2018": {
        "name": "Typhoon Mangkhut (2018)",
        "category": "Tropical cyclone",
        "baseline_start": "2018-09-15T00:00:00Z",
        "baseline_end": "2018-09-17T00:00:00Z",
        "peak_start": "2018-09-16T00:00:00Z",
        "peak_end": "2018-09-16T12:00:00Z",
        "start": "2018-09-15T00:00:00Z",
        "end": "2018-09-17T00:00:00Z",
    },
    "HRAIN2023": {
        "name": "Black Rainstorm (2023)",
        "category": "Heavy rain",
        "baseline_start": "2023-09-06T00:00:00Z",
        "baseline_end": "2023-09-09T00:00:00Z",
        "peak_start": "2023-09-07T14:00:00Z",
        "peak_end": "2023-09-08T08:00:00Z",
        "start": "2023-09-06T00:00:00Z",
        "end": "2023-09-09T00:00:00Z",
    },
    "HRAIN2025": {
        "name": "Black Rainstorm (2025)",
        "category": "Heavy rain",
        "baseline_start": "2025-08-03T00:00:00Z",
        "baseline_end": "2025-08-06T00:00:00Z",
        "peak_start": "2025-08-04T21:00:00Z",
        "peak_end": "2025-08-05T12:00:00Z",
        "start": "2025-08-03T00:00:00Z",
        "end": "2025-08-06T00:00:00Z",
    },
    "HEAT2022": {
        "name": "Heatwave (2022)",
        "category": "Extreme heat",
        "baseline_start": "2022-07-22T00:00:00Z",
        "baseline_end": "2022-07-25T00:00:00Z",
        "peak_start": "2022-07-23T00:00:00Z",
        "peak_end": "2022-07-24T12:00:00Z",
        "start": "2022-07-22T00:00:00Z",
        "end": "2022-07-25T00:00:00Z",
    },
    "HEAT2024": {
        "name": "Heatwave (2024)",
        "category": "Extreme heat",
        "baseline_start": "2024-08-27T00:00:00Z",
        "baseline_end": "2024-08-29T00:00:00Z",
        "peak_start": "2024-08-28T00:00:00Z",
        "peak_end": "2024-08-28T12:00:00Z",
        "start": "2024-08-27T00:00:00Z",
        "end": "2024-08-29T00:00:00Z",
    },
}

# ---------------------------------------------------------------------------
# Required submission time coverage, per event x resolution category.
# ---------------------------------------------------------------------------

REQUIRED_PERIODS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "MANGKHUT2018": {
        "km": ("2018-09-15T00:00:00Z", "2018-09-17T00:00:00Z"),
        "subkm": ("2018-09-16T00:00:00Z", "2018-09-17T00:00:00Z"),
    },
    "HRAIN2023": {
        "km": ("2023-09-06T00:00:00Z", "2023-09-09T00:00:00Z"),
        "subkm": ("2023-09-07T14:00:00Z", "2023-09-08T20:00:00Z"),
    },
    "HRAIN2025": {
        "km": ("2025-08-03T00:00:00Z", "2025-08-06T00:00:00Z"),
        "subkm": ("2025-08-04T21:00:00Z", "2025-08-06T00:00:00Z"),
    },
    "HEAT2022": {
        "km": ("2022-07-22T00:00:00Z", "2022-07-25T00:00:00Z"),
        "subkm": ("2022-07-23T00:00:00Z", "2022-07-25T00:00:00Z"),
    },
    "HEAT2024": {
        "km": ("2024-08-27T00:00:00Z", "2024-08-29T00:00:00Z"),
        "subkm": ("2024-08-28T00:00:00Z", "2024-08-29T00:00:00Z"),
    },
}

# ---------------------------------------------------------------------------
# Init-* label -> authoritative initialization timestamp, per event.
# ---------------------------------------------------------------------------
# These values are transcribed verbatim from the agreed protocol guide's
# 00Z initialization-cycle table. Init-5 .. Init-1 are NOT equally spaced
# (they follow the guide's 00Z cycle, not peak - N*24h), so do not derive
# them arithmetically. Init-0.5 and Init-0.25 do satisfy
# peak_start - 12h / peak_start - 6h respectively; that invariant is
# checked by tests, not relied upon here.

INIT_LABELS: List[str] = [
    "Init-5",
    "Init-4",
    "Init-3",
    "Init-2",
    "Init-1",
    "Init-0.5",
    "Init-0.25",
    "Init-0",
]

INIT_TIMES: Dict[str, Dict[str, str]] = {
    "MANGKHUT2018": {
        "Init-5": "2018-09-11T00:00:00Z",
        "Init-4": "2018-09-12T00:00:00Z",
        "Init-3": "2018-09-13T00:00:00Z",
        "Init-2": "2018-09-14T00:00:00Z",
        "Init-1": "2018-09-15T00:00:00Z",
        "Init-0.5": "2018-09-15T12:00:00Z",
        "Init-0.25": "2018-09-15T18:00:00Z",
    },
    "HRAIN2023": {
        "Init-5": "2023-09-02T00:00:00Z",
        "Init-4": "2023-09-03T00:00:00Z",
        "Init-3": "2023-09-04T00:00:00Z",
        "Init-2": "2023-09-05T00:00:00Z",
        "Init-1": "2023-09-06T00:00:00Z",
        "Init-0.5": "2023-09-07T02:00:00Z",
        "Init-0.25": "2023-09-07T08:00:00Z",
    },
    "HRAIN2025": {
        "Init-5": "2025-07-30T00:00:00Z",
        "Init-4": "2025-07-31T00:00:00Z",
        "Init-3": "2025-08-01T00:00:00Z",
        "Init-2": "2025-08-02T00:00:00Z",
        "Init-1": "2025-08-03T00:00:00Z",
        "Init-0.5": "2025-08-04T09:00:00Z",
        "Init-0.25": "2025-08-04T15:00:00Z",
    },
    "HEAT2022": {
        "Init-5": "2022-07-18T00:00:00Z",
        "Init-4": "2022-07-19T00:00:00Z",
        "Init-3": "2022-07-20T00:00:00Z",
        "Init-2": "2022-07-21T00:00:00Z",
        "Init-1": "2022-07-22T00:00:00Z",
        "Init-0.5": "2022-07-22T12:00:00Z",
        "Init-0.25": "2022-07-22T18:00:00Z",
    },
    "HEAT2024": {
        "Init-5": "2024-08-23T00:00:00Z",
        "Init-4": "2024-08-24T00:00:00Z",
        "Init-3": "2024-08-25T00:00:00Z",
        "Init-2": "2024-08-26T00:00:00Z",
        "Init-1": "2024-08-27T00:00:00Z",
        "Init-0.5": "2024-08-27T12:00:00Z",
        "Init-0.25": "2024-08-27T18:00:00Z",
    },
}

# ---------------------------------------------------------------------------
# Experiment directory names (D2: canonical IDs, not "AN-ERA5").
# ---------------------------------------------------------------------------

EXPERIMENTS: List[str] = [
    "ERA5-AN",
    "FNL-AN",
    "JRA55-AN",
    "UKMO-AN",
    "OTHER-AN",
    "GFS-FC",
    "UKMO-FC",
    "OTHER-FC",
]

# ---------------------------------------------------------------------------
# Core grid / variable / attribute contract.
# Copied verbatim from portal_lib.py -- values and order unchanged.
# ---------------------------------------------------------------------------

CORE_GRID = {
    "lat_south": 22.12,
    "lon_west": 113.82,
    "resolution_degrees": 9.7 / 3600.0,
    "nlat": 171,
    "nlon": 234,
}

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
    "SWUP",
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
]

# Radiation fields. Recommended, not required: a submission missing them is
# accepted, and the uploader is told which ones were not found.
RECOMMENDED_RADIATION_VARS = ["SWDOWN", "SWNET", "SWDIR", "LWDOWN", "LWNET"]

# Pressure-level fields. Also recommended rather than required, on the same
# terms. Vertical motion may be supplied as pressure velocity or as geometric
# velocity; either counts.
RECOMMENDED_3D_LEVEL_VARS = ["T", "Z", "RH", "U", "V", "Q"]
RECOMMENDED_3D_ALTERNATIVES = [("OMEGA", "W")]
RECOMMENDED_3D_LEVELS_HPA = [850, 500, 200]

THREE_D_VARS = ["T", "Z", "RH", "U", "V", "Q", "OMEGA", "W"]

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
    "forecast_initialization_time",
    "forecast_lead_time_hours",
    "forcing_mode",
    "forcing_source",
    "forcing_data",
    "forcing_data_version",
    "forcing_resolution",
    "forcing_update_interval",
    "horizontal_resolution",
    "contact",
    "creator_name",
    "creation_date",
    "version",
]

ARCHIVE_TIME_ATTRS = (
    "simulation_start_time",
    "initialization_time",
    "forecast_initialization_time",
    "forecast_lead_time_hours",
)

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
    r"^([A-Za-z0-9._]+(?:-[A-Za-z0-9._]+)*)-(AN|FC)-"
    r"([A-Za-z0-9._]+)-("
    + "|".join(EVENTS.keys())
    + r")-(\d{14})"
    r"(?:_(?!r[0-9]{2,}\.nc$)((?:(?!_r[0-9]{2,}\.nc$)[A-Za-z0-9._-])+))?"
    r"(?:_r([0-9]{2,}))?\.nc$"
)

# ---------------------------------------------------------------------------
# Archive / directory naming (v3 submission structure).
# ---------------------------------------------------------------------------
# Tokens use [A-Z0-9]+ (uppercase letters and digits only): a hyphen is a
# field separator, so it cannot appear inside a token (e.g. "WRF-ARW" must
# be written "WRFARW"), matching the convention already used by
# RUMI_FILENAME_RE / README.

ARCHIVE_NAME_RE = re.compile(
    r"^([A-Z0-9]+)-([A-Z0-9]+)-("
    + "|".join(EVENTS.keys())
    + r")-([A-Z0-9]+)\.(tar\.gz|zip)$"
)
ARCHIVE_NAME_PATTERN = ARCHIVE_NAME_RE.pattern

INIT_DIR_RE = re.compile(r"^Init-(5|4|3|2|1|0\.5|0\.25|0|\d{10})$")


def parse_utc(value: Optional[str]) -> Optional[dt.datetime]:
    """Parse an ISO-8601 timestamp (optionally with a trailing 'Z') into an
    aware ``datetime``. Returns ``None`` if ``value`` is falsy or malformed.

    Behavior matches ``portal_lib.parse_utc``.
    """
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_z(moment: dt.datetime) -> str:
    """Format an aware ``datetime`` as ``"YYYY-MM-DDTHH:MM:SSZ"`` (UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    else:
        moment = moment.astimezone(dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_archive_name(name: str) -> Optional[Dict[str, str]]:
    """Parse a v3 archive file name.

    Expected form:
    ``<INST>-<MODEL>-<EVENT>-<POC>.(tar.gz|zip)``

    Returns a dict with keys ``institution``, ``model``, ``event``, ``poc``,
    ``config``, ``version``, ``extension``, ``stem`` (the compatibility config
    and version values are empty because they now belong in the PDF), with
    its extension removed, e.g. ``.tar.gz`` is removed as a whole, not just
    ``.gz``), or ``None`` if ``name`` does not match.
    """
    match = ARCHIVE_NAME_RE.match(name or "")
    if not match:
        return None
    institution, model, event, poc, extension = match.groups()
    stem = name[: -(len(extension) + 1)]
    return {
        "institution": institution,
        "model": model,
        "event": event,
        "poc": poc,
        "config": "",
        "version": "",
        "extension": extension,
        "stem": stem,
    }


def parse_absolute_init_label(init_label: str) -> Optional[str]:
    """Parse an absolute ``Init-<YYYYMMDDHH>`` label into an ISO timestamp.

    Example: ``"Init-2025080300"`` -> ``"2025-08-03T00:00:00Z"``.
    Returns ``None`` if ``init_label`` is not an absolute-form label (or the
    digits do not form a valid date/hour).
    """
    match = re.fullmatch(r"Init-(\d{10})", init_label or "")
    if not match:
        return None
    try:
        moment = dt.datetime.strptime(match.group(1), "%Y%m%d%H").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        return None
    return iso_z(moment)


def init_time_for(event: str, init_label: str) -> Optional[str]:
    """Return the authoritative initialization timestamp (ISO string) for
    ``event``'s ``init_label``.

    ``Init-0`` (participant-defined single AN initialization) and absolute
    labels such as ``Init-2025080300`` (whose timestamp is already encoded
    in the label itself) both return ``None``. Unknown events or unknown
    labels also return ``None``.
    """
    if event not in INIT_TIMES:
        return None
    if init_label == "Init-0":
        return None
    if parse_absolute_init_label(init_label) is not None:
        return None
    return INIT_TIMES[event].get(init_label)


def required_period(event: str, category: str) -> Optional[Tuple[str, str]]:
    """Return the ``(start_iso, end_iso)`` required submission period for
    ``event`` at resolution ``category`` (``"km"`` or ``"subkm"``).

    Returns ``None`` for an unknown event or category.
    """
    if category not in ("km", "subkm"):
        return None
    periods = REQUIRED_PERIODS.get(event)
    if periods is None:
        return None
    return periods.get(category)


def resolution_category(horizontal_resolution: Optional[str]) -> Optional[str]:
    """Classify a NetCDF ``horizontal_resolution`` global attribute value
    as ``"km"`` or ``"subkm"``.

    Parses a leading numeric value and a ``km``/``m`` unit, converts to
    meters, and returns ``"subkm"`` for values strictly under 1000 m and
    ``"km"`` for values at or above 1000 m. Handles inputs such as
    ``"1 km"``, ``"1km"``, ``"0.5 km"``, ``"500 m"``, ``"500m"``,
    ``"250 m"``, ``"1000 m"``, ``"~1 km"``, ``"1.0 km"``. Returns ``None``
    for empty, ``None``, or unparseable input.
    """
    if not horizontal_resolution:
        return None
    text = str(horizontal_resolution).strip()
    if not text:
        return None
    text = text.lstrip("~≈").strip()
    match = re.match(
        r"^([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(km|kilometers?|m|meters?)$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    meters = value * 1000.0 if unit.startswith("k") else value
    return "subkm" if meters < 1000.0 else "km"


def expected_timestamps(
    event: str, category: str, actual_init_time: Optional[str] = None
) -> List[str]:
    """Return the list of required hourly timestamps (ISO strings,
    inclusive of both ends) for ``event`` at resolution ``category``.

    If ``actual_init_time`` is given and is strictly later than the
    required period's start, the returned series starts at
    ``actual_init_time`` instead (the required end timestamp is unchanged).
    This implements the FC staggered-initialization rule. If
    ``actual_init_time`` is later than the required end timestamp, an empty
    list is returned. Returns an empty list for an unknown event/category.
    """
    period = required_period(event, category)
    if period is None:
        return []
    start = parse_utc(period[0])
    end = parse_utc(period[1])
    if start is None or end is None:
        return []
    if actual_init_time:
        actual = parse_utc(actual_init_time)
        if actual is not None and actual > start:
            start = actual
    if start > end:
        return []
    step = dt.timedelta(hours=OUTPUT_INTERVAL_HOURS)
    timestamps = []
    current = start
    while current <= end:
        timestamps.append(iso_z(current))
        current += step
    return timestamps


# ---------------------------------------------------------------------------
# Archive rules shared by the portal and the downloadable validator.
# These are pure functions over paths and NetCDF global attributes: no I/O, no
# database, no NetCDF tooling. Keeping them here is what lets rumi_validate.py
# inline this module and give participants exactly the portal's verdict.
# ---------------------------------------------------------------------------

def parse_rumi_filename(name):
    match = RUMI_FILENAME_RE.match(name)
    if not match:
        return None
    forcing, mode, model, event, stamp, member, version = match.groups()
    try:
        ts = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return {
        "experiment": f"{forcing}-{mode}",
        "model": model,
        "event": event,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "member": member or "",
        "version": version or "",
    }


DOCUMENTATION_EXTENSIONS = (".pdf", ".docx")
INIT_TOLERANCE_HOURS = 6

# GFS only publishes standard cycles, and Init-0.5 / Init-0.25 as currently
# defined do not always land on one. Until that is settled with Lewis, a
# mismatch on these two labels is reported but does not reject the submission.
PROVISIONAL_INIT_LABELS = ("Init-0.5", "Init-0.25")
MAX_REPORTED_EXAMPLES = 3
MAX_REPORTED_MISSING_TIMESTAMPS = 10


def archive_stem(filename):
    """Return an archive name with its extension removed, treating '.tar.gz' as one unit."""
    parsed = parse_archive_name(filename)
    if parsed:
        return parsed["stem"]
    lower = filename.lower()
    for extension in (".tar.gz", ".zip"):
        if lower.endswith(extension):
            return filename[: -len(extension)]
    return filename


class IssueLog:
    """Collect per-file findings and report them once per distinct problem.

    A single systematic mistake in a submission affects every file in the
    archive. Reporting it several hundred times would bury the other findings
    and bloat the stored validation record, so identical messages are folded
    into one line carrying a count and a few example paths.
    """

    def __init__(self):
        self._groups = {}
        self._order = []

    def add(self, message, example=None):
        if message not in self._groups:
            self._groups[message] = []
            self._order.append(message)
        if example is not None:
            self._groups[message].append(example)

    def messages(self):
        lines = []
        for message in self._order:
            examples = self._groups[message]
            if not examples:
                lines.append(message)
                continue
            shown = ", ".join(examples[:MAX_REPORTED_EXAMPLES])
            if len(examples) > MAX_REPORTED_EXAMPLES:
                lines.append(
                    f"{message} ({len(examples)} files, for example {shown})"
                )
            else:
                lines.append(f"{message} ({shown})")
        return lines

    def __bool__(self):
        return bool(self._order)


def init_label_is_valid(init_label):
    if not INIT_DIR_RE.match(init_label):
        return False
    if init_label.startswith("Init-") and len(init_label) == len("Init-YYYYMMDDHH"):
        return parse_absolute_init_label(init_label) is not None
    return True


def validate_archive_structure(names, filename):
    """Validate archive layout from member paths alone.

    Runs in milliseconds and needs no NetCDF tooling, so a misnamed archive or
    a wrong directory level is reported to the participant immediately instead
    of after several minutes of per-file checking.
    """
    errors = IssueLog()
    warnings = IssueLog()
    layout = {}
    summary = {"documentation_files": 0, "top_level_directories": []}

    archive = parse_archive_name(filename)
    summary["archive"] = archive
    if not archive:
        errors.add(
            "Archive name must be <INST>-<MODEL>-<EVENT>-<POC>.tar.gz or .zip, "
            "for example HKUST-MPAS-HRAIN2025-SHI.tar.gz. Fields must be "
            "uppercase letters and digits without hyphens, so a model such as "
            "WRF-ARW is written WRFARW."
        )
        return {
            "errors": errors.messages(),
            "warnings": warnings.messages(),
            "summary": summary,
            "layout": layout,
        }

    stem = archive["stem"]
    unsafe = [
        name for name in names if name.startswith("/") or ".." in Path(name).parts
    ]
    if unsafe:
        errors.add("Archive contains unsafe paths.", unsafe[0])

    tops = sorted({Path(name).parts[0] for name in names if Path(name).parts})
    summary["top_level_directories"] = tops
    if tops != [stem]:
        errors.add(
            f"The archive must contain exactly one top-level directory named {stem}. "
            f"Found: {', '.join(tops) or 'nothing'}."
        )

    netcdf_names = [name for name in names if name.lower().endswith(".nc")]
    if not netcdf_names:
        errors.add("Archive does not contain any .nc files.")

    documentation = [
        name
        for name in names
        if len(Path(name).parts) == 2
        and Path(name).parts[0] == stem
        and name.lower().endswith(DOCUMENTATION_EXTENSIONS)
    ]
    summary["documentation_files"] = len(documentation)
    if not documentation:
        errors.add(
            "Participant_Model_Documentation.pdf (or .docx) must be present at "
            "the top level of the archive."
        )

    for name in names:
        if not name.lower().endswith(".nc"):
            continue
        parts = Path(name).parts
        if len(parts) != 4 or parts[0] != stem:
            errors.add(
                "Every NetCDF file must be stored as "
                "<archive>/<EXPERIMENT>/<Init-*>/<file>.nc.",
                name,
            )
            continue
        _, experiment, init_label, member_name = parts
        member_ok = True
        if experiment not in EXPERIMENTS:
            errors.add(
                "Experiment directories must use the canonical RUMI identifier, "
                "for example ERA5-AN or GFS-FC, not the reversed form.",
                name,
            )
            member_ok = False
        if not init_label_is_valid(init_label):
            errors.add(
                "Initialization directories must be Init-5, Init-4, Init-3, "
                "Init-2, Init-1, Init-0.5, Init-0.25, Init-0, or an absolute "
                "Init-YYYYMMDDHH.",
                name,
            )
            member_ok = False

        parsed_name = parse_rumi_filename(member_name)
        if not parsed_name:
            errors.add(
                "File name must follow <experiment>-<Model>-<Event>-"
                "<YYYYMMDDHHMMSS>[_member][_rNN].nc.",
                name,
            )
            member_ok = False
        else:
            if experiment in EXPERIMENTS and parsed_name["experiment"] != experiment:
                errors.add(
                    "File name experiment does not match the experiment directory "
                    "it is stored in.",
                    name,
                )
                member_ok = False
            if parsed_name["model"].upper() != archive["model"]:
                errors.add(
                    f"File name model does not match the archive model "
                    f"{archive['model']}.",
                    name,
                )
                member_ok = False
            if parsed_name["event"] != archive["event"]:
                errors.add(
                    f"An archive holds one event only. This file belongs to "
                    f"{parsed_name['event']}, but the archive is for "
                    f"{archive['event']}.",
                    name,
                )
                member_ok = False

        if member_ok:
            layout[name] = {
                "experiment": experiment,
                "init": init_label,
                "file_name": member_name,
                "timestamp": parsed_name["timestamp"],
            }

    return {
        "errors": errors.messages(),
        "warnings": warnings.messages(),
        "summary": summary,
        "layout": layout,
    }


def expected_initialization(event, experiment, init_label):
    """Return (expected_iso, attribute_name) for an initialization directory."""
    attribute = (
        "forecast_initialization_time"
        if experiment.endswith("-FC")
        else "initialization_time"
    )
    if init_label == "Init-0":
        return None, attribute
    absolute = parse_absolute_init_label(init_label)
    if absolute:
        return absolute, attribute
    return init_time_for(event, init_label), attribute


def validate_init_directory(event, experiment, init_label, members):
    """Validate one <EXPERIMENT>/<Init-*> directory as a whole.

    ``members`` is a list of dicts with ``name``, ``timestamp`` and
    ``time_metadata`` (the global attributes read from each file).
    """
    errors = IssueLog()
    warnings = IssueLog()
    where = f"{experiment}/{init_label}"

    expected_init, attribute = expected_initialization(event, experiment, init_label)
    declared = sorted(
        {
            (member["time_metadata"] or {}).get(attribute)
            for member in members
            if (member["time_metadata"] or {}).get(attribute)
        }
    )
    if len(declared) > 1:
        errors.add(
            f"{where}: every file in one initialization directory must declare the "
            f"same {attribute}. Found {', '.join(declared)}."
        )
    elif not declared:
        warnings.add(f"{where}: no file declares {attribute}.")

    actual_init = declared[0] if len(declared) == 1 else expected_init
    if expected_init and len(declared) == 1:
        expected_moment = parse_utc(expected_init)
        actual_moment = parse_utc(declared[0])
        if actual_moment is None:
            errors.add(f"{where}: {attribute} is not a valid timestamp: {declared[0]}.")
        else:
            offset_hours = abs(
                (actual_moment - expected_moment).total_seconds()
            ) / 3600.0
            if offset_hours > INIT_TOLERANCE_HOURS:
                message = (
                    f"{where}: {attribute} is {declared[0]}, which is "
                    f"{offset_hours:.0f} hours from the {init_label} time "
                    f"{expected_init} defined for {event}."
                )
                if init_label in PROVISIONAL_INIT_LABELS:
                    warnings.add(
                        message
                        + " This label is provisional pending confirmation of "
                        "the available forecast cycles, so it is not rejected."
                    )
                else:
                    errors.add(message)
                    actual_init = expected_init
            elif offset_hours > 0:
                warnings.add(
                    f"{where}: {attribute} is {declared[0]} rather than the "
                    f"{init_label} time {expected_init}, which is accepted as the "
                    f"nearest available forecast cycle."
                )

    resolutions = [
        (member["time_metadata"] or {}).get("horizontal_resolution")
        for member in members
    ]
    category = None
    for value in resolutions:
        category = resolution_category(value)
        if category:
            break
    if not category:
        category = "km"
        warnings.add(
            f"{where}: horizontal_resolution could not be interpreted, so the "
            f"~1 km required period was assumed."
        )

    if init_label == "Init-0":
        required_start = (required_period(event, category) or (None, None))[0]
        if actual_init and required_start and parse_utc(actual_init) > parse_utc(required_start):
            warnings.add(
                f"{where}: initialization_time {actual_init} is later than the "
                f"required period start {required_start}."
            )
        expected_series = expected_timestamps(event, category)
    else:
        expected_series = expected_timestamps(event, category, actual_init)

    present = {}
    for member in members:
        present.setdefault(member["timestamp"], []).append(member["name"])
    duplicates = sorted(stamp for stamp, names in present.items() if len(names) > 1)
    for stamp in duplicates:
        errors.add(f"{where}: two files carry the timestamp {stamp}.")

    coverage = {
        "category": category,
        "initialization": actual_init,
        "files": len(members),
        "expected": len(expected_series),
    }
    if expected_series:
        required_start, required_end = expected_series[0], expected_series[-1]
        coverage["required_start"] = required_start
        coverage["required_end"] = required_end
        if required_end not in present:
            errors.add(
                f"{where}: the required final timestamp {required_end} is missing."
            )
        if required_start not in present:
            warnings.add(
                f"{where}: the required period starts at {required_start}, which is "
                f"not present. This is accepted because accumulated fields are not "
                f"meaningful at the first output step."
            )
        missing = [
            stamp
            for stamp in expected_series[1:-1]
            if stamp not in present
        ]
        coverage["missing"] = len(missing)
        if missing:
            shown = ", ".join(missing[:MAX_REPORTED_MISSING_TIMESTAMPS])
            more = (
                f" and {len(missing) - MAX_REPORTED_MISSING_TIMESTAMPS} more"
                if len(missing) > MAX_REPORTED_MISSING_TIMESTAMPS
                else ""
            )
            warnings.add(
                f"{where}: {len(missing)} hourly timestamps are missing from the "
                f"required period: {shown}{more}."
            )
    else:
        warnings.add(
            f"{where}: no required period could be derived for {event}."
        )

    stamps = sorted(present)
    coverage["first"] = stamps[0] if stamps else None
    coverage["last"] = stamps[-1] if stamps else None
    return {
        "errors": errors.messages(),
        "warnings": warnings.messages(),
        "coverage": coverage,
    }


def header_has_var(header, name):
    return re.search(r"\b(?:byte|char|short|int|int64|float|double)\s+" + re.escape(name) + r"\s*\(", header) is not None


def header_dim(header, name):
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*(\d+)\s*;", header)
    return int(match.group(1)) if match else None


def header_attr(header, name):
    match = re.search(
        r":\s*" + re.escape(name) + r"\s*=\s*(?:\"([^\"]*)\"|([^;\r\n]+))\s*;",
        header,
    )
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2).strip()


def parse_lead_time_hours(value):
    if value is None:
        return None
    match = re.match(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", str(value))
    if not match:
        return None
    suffix = str(value)[match.end():].strip().lower()
    if suffix not in {
        "",
        "h",
        "hr",
        "hrs",
        "hour",
        "hours",
        "b",
        "s",
        "us",
        "l",
        "ll",
        "ul",
        "ull",
        "f",
        "d",
    }:
        return None
    hours = float(match.group(1))
    if hours < 0 or not hours.is_integer():
        return None
    return int(hours)


def validate_timestamp_in_event(timestamp_iso, event):
    ts = parse_utc(timestamp_iso)
    if not ts or event not in EVENTS:
        return None
    start = parse_utc(EVENTS[event]["start"])
    end = parse_utc(EVENTS[event]["end"])
    return start <= ts <= end


KNOWN_ATTRIBUTES = tuple(
    dict.fromkeys(
        list(REQUIRED_GLOBAL_ATTRS)
        + list(PHYSICS_ATTRS)
        + ["model", "horizontal_resolution", "vertical_levels", "model_top_pressure"]
    )
)

# Every variable a reader is asked to look for. A name missing from this tuple
# is invisible to validation no matter what the file contains, so the mandatory
# groups must all be listed here.
ALL_KNOWN_VARS = tuple(
    dict.fromkeys(
        list(CORE_2D_VARS)
        + list(RECOMMENDED_RADIATION_VARS)
        + list(RECOMMENDED_3D_LEVEL_VARS)
        + list(RECOMMENDED_2D_VARS)
        + list(THREE_D_VARS)
    )
)


def netcdf_facts_from_header(kind, header, coordinates):
    """Turn ``ncdump`` output into the structured facts the rules work on.

    The portal reads files with ncdump; the downloadable validator may instead
    read them with the netCDF4 package. Both produce this same dict, so both
    reach the same verdict.
    """
    return {
        "kind": kind,
        "attributes": {name: header_attr(header, name) for name in KNOWN_ATTRIBUTES},
        "variables": sorted(
            name for name in ALL_KNOWN_VARS if header_has_var(header, name)
        ),
        "dimensions": {
            "lat": header_dim(header, "lat"),
            "lon": header_dim(header, "lon"),
        },
        "lat": list(coordinates.get("lat") or []),
        "lon": list(coordinates.get("lon") or []),
    }


def validate_netcdf_facts(filename, facts, metadata=None):
    """Judge one submitted NetCDF file. Pure: no file access, no tooling.

    ``facts`` is the dict produced by :func:`netcdf_facts_from_header` or by an
    equivalent netCDF4-based reader. Passing ``None`` validates the file name
    alone, which is what the portal does when a file could not be opened.
    """
    metadata = metadata or {}
    errors = []
    warnings = []
    summary = {}

    parsed = parse_rumi_filename(filename)
    if not parsed:
        errors.append(
            "File name must follow <experiment>-<Model>-<Event>-"
            "<YYYYMMDDHHMMSS>[_member][_rNN].nc, for example "
            "ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc."
        )
    else:
        summary["filename"] = parsed
        if parsed["experiment"] not in EXPERIMENTS:
            errors.append(
                f"File name experiment {parsed['experiment']} is not a RUMI "
                "experiment identifier. Use one of: " + ", ".join(EXPERIMENTS) + "."
            )
        if re.fullmatch(r"v[0-9]{2,}", parsed["member"] or ""):
            warnings.append(
                f"'_{parsed['member']}' was read as a member label, not a "
                "version. Versions are written _r" + parsed["member"][1:] + "."
            )
        if metadata.get("experiment") and parsed["experiment"].upper() != metadata.get("experiment", "").upper():
            errors.append("File name experiment does not match the submitted metadata.")
        if metadata.get("model") and parsed["model"].lower() != metadata.get("model", "").lower():
            errors.append("File name model does not match the submitted metadata.")
        if metadata.get("event") and parsed["event"] != metadata.get("event"):
            errors.append("File name event does not match the submitted metadata.")
        if validate_timestamp_in_event(parsed["timestamp"], parsed["event"]) is False:
            warnings.append("File timestamp is outside the baseline simulation period for the selected event.")

    if facts is None:
        return {"errors": errors, "warnings": warnings, "summary": summary}

    kind = facts.get("kind") or ""
    summary["netcdf_kind"] = kind
    if "netCDF-4" not in kind:
        errors.append("File is readable by ncdump but is not NetCDF4.")

    present = set(facts.get("variables") or [])
    attributes = facts.get("attributes") or {}

    def attr(name):
        return attributes.get(name)

    missing_core = [name for name in CORE_2D_VARS if name not in present]
    if missing_core:
        errors.append("Missing core 2D variables: " + ", ".join(missing_core))

    # Recommended groups never reject a submission. They are reported so the
    # uploader knows exactly what was not found in the file.
    missing_radiation = [
        name for name in RECOMMENDED_RADIATION_VARS if name not in present
    ]
    if missing_radiation:
        warnings.append(
            "Recommended radiation variables not found: "
            + ", ".join(missing_radiation)
            + ". The submission is accepted; please include them if your model "
            "produces them."
        )

    missing_3d = [name for name in RECOMMENDED_3D_LEVEL_VARS if name not in present]
    for alternatives in RECOMMENDED_3D_ALTERNATIVES:
        if not any(name in present for name in alternatives):
            missing_3d.append(" or ".join(alternatives))
    if missing_3d:
        warnings.append(
            "Recommended pressure-level variables not found on the "
            + ", ".join(f"{level} hPa" for level in RECOMMENDED_3D_LEVELS_HPA)
            + " levels: "
            + ", ".join(missing_3d)
            + ". The submission is accepted; please include them if your model "
            "produces them."
        )

    present_recommended = [name for name in RECOMMENDED_2D_VARS if name in present]
    present_3d = [name for name in THREE_D_VARS if name in present]
    summary["recommended_2d_count"] = len(present_recommended)
    summary["three_d_present"] = present_3d
    summary["time_metadata"] = {
        name: attr(name) for name in ARCHIVE_TIME_ATTRS
    }
    summary["time_metadata"]["horizontal_resolution"] = attr("horizontal_resolution")

    lat = (facts.get("dimensions") or {}).get("lat")
    lon = (facts.get("dimensions") or {}).get("lon")
    summary["dimensions"] = {
        "lat": lat,
        "lon": lon,
    }
    if lat != CORE_GRID["nlat"] or lon != CORE_GRID["nlon"]:
        errors.append(
            "Standard core grid dimensions must be 171 lat by 234 lon "
            "(9.7 arc-seconds)."
        )

    expected_coordinates = {
        "lat": (CORE_GRID["lat_south"], CORE_GRID["nlat"]),
        "lon": (CORE_GRID["lon_west"], CORE_GRID["nlon"]),
    }
    for name, (start, count) in expected_coordinates.items():
        values = facts.get(name) or []
        valid = len(values) == count and all(
            abs(value - (start + index * CORE_GRID["resolution_degrees"])) <= 1e-7
            for index, value in enumerate(values)
        )
        if not valid:
            if len(values) > 1:
                mean_spacing_arcsec = (
                    (values[-1] - values[0]) / (len(values) - 1) * 3600
                )
                received = (
                    f" Received {len(values)} points from {values[0]:.8f} to "
                    f"{values[-1]:.8f}, with mean spacing "
                    f"{mean_spacing_arcsec:.6f} arc-seconds."
                )
            else:
                received = f" Received {len(values)} coordinate values."
            errors.append(
                f"{name} coordinates must follow the RUMI 9.7 arc-second "
                f"core grid ({count} points starting at {start}).{received}"
            )

    missing_attrs = [name for name in REQUIRED_GLOBAL_ATTRS if attr(name) is None]
    if missing_attrs:
        warnings.append("Missing required global attributes: " + ", ".join(missing_attrs))

    missing_physics = [name for name in PHYSICS_ATTRS if attr(name) is None]
    if missing_physics:
        warnings.append("Missing physics/surface documentation attributes: " + ", ".join(missing_physics))

    conventions = attr("Conventions")
    if conventions and "CF-1.8" not in conventions:
        warnings.append("Conventions attribute does not include CF-1.8.")

    attr_event = attr("event")
    if parsed and attr_event and attr_event != parsed["event"]:
        errors.append("Global attribute event does not match file name.")

    attr_experiment = attr("experiment")
    if parsed and attr_experiment:
        if attr_experiment.upper() != parsed["experiment"].upper():
            errors.append("Global attribute experiment does not match file name.")

    attr_model = attr("model") or attr("source")
    if parsed and attr_model and attr_model.lower() != parsed["model"].lower():
        warnings.append(
            "Global attribute model/source does not match the model in the file name."
        )

    return {"errors": errors, "warnings": warnings, "summary": summary}

# ============================================================================
# END inlined rules
# ============================================================================

# ---------------------------------------------------------------------------
# CLI: reads files (directory tree or .tar.gz/.zip archive) and NetCDF
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
    if lower.endswith(".tar.gz"):
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
    if target_path.is_file() and lower.endswith((".tar.gz", ".zip")):
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


def _ncdump_candidates():
    """Every ncdump worth trying, best first, de-duplicated.

    shutil.which() returns only the first match on PATH, which is not enough:
    a conda environment can shadow a working system ncdump with a broken one.
    """
    seen = set()
    ordered = []

    def offer(path):
        if not path:
            return
        path = str(path)
        if path in seen:
            return
        seen.add(path)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            ordered.append(path)

    offer(os.environ.get("RUMI_NCDUMP"))
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory:
            offer(os.path.join(directory, "ncdump"))
    for fallback in ("/usr/bin/ncdump", "/usr/local/bin/ncdump", "/opt/homebrew/bin/ncdump"):
        offer(fallback)
    return ordered


def _ncdump_is_usable(path):
    """Probe an ncdump binary without handing it a data file.

    Running it with no arguments prints a usage message; a binary that cannot
    load its libraries prints a linker error instead. Probing this way means a
    genuinely corrupt submission file can never be mistaken for broken tooling.
    Returns (ok, detail).
    """
    try:
        proc = subprocess.run(
            [path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = proc.stdout or ""
    if "[-" in output:
        return True, ""
    return False, (output.strip().splitlines() or ["produced no usage message"])[0]


def _find_ncdump():
    """Return the first ncdump that actually runs, or None.

    A broken ncdump used to surface as "file could not be read" on every single
    file in the submission, which points the participant at their data instead
    of at their toolchain.
    """
    for candidate in _ncdump_candidates():
        ok, _ = _ncdump_is_usable(candidate)
        if ok:
            return candidate
    return None


def _ncdump_failure_report():
    lines = []
    for candidate in _ncdump_candidates():
        ok, detail = _ncdump_is_usable(candidate)
        if not ok:
            lines.append("  " + candidate + ": " + detail)
    return lines


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
    broken = _ncdump_failure_report()
    if broken:
        # ncdump exists but cannot run. Say so plainly: this is a toolchain
        # problem, not a problem with the files being submitted.
        detail = "\n".join(broken)
        if choice == "ncdump":
            raise ReaderUnavailable(
                "every ncdump found on this machine failed to run:\n" + detail
                + "\nInstall the netCDF4 Python package ('pip install netCDF4') "
                "or point RUMI_NCDUMP at a working ncdump."
            )
        raise ReaderUnavailable(
            "no NetCDF reader is available. The netCDF4 Python package is not "
            "installed, and every ncdump found on this machine failed to run:\n"
            + detail
            + "\nInstall the netCDF4 Python package ('pip install netCDF4') or "
            "point RUMI_NCDUMP at a working ncdump."
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
            f".tar.gz/.zip archive.",
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
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
            ".tar.gz/.zip archive) against the same rules the portal "
            "uses, so problems can be found and fixed before uploading."
        ),
    )
    parser.add_argument(
        "path",
        help="Path to an extracted submission directory, or a .tar.gz/.zip archive.",
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


if __name__ == "__main__":
    sys.exit(main())
