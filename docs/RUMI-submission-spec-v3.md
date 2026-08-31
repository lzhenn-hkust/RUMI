# RUMI Phase 1 Submission Specification v3

    RULES_VERSION: 2026-08-rumi-v3.2
    Status:        agreed in principle; open items listed in section 10
    Supersedes:    the `lead_NNNh` archive layout described in README.md before this version

This document is the single source of truth for how a RUMI Phase 1 submission is
named, structured, and validated. The upload portal, the downloadable validator
(`rumi_validate.py`), and the participant instructions are all generated from the
tables below. If any other document disagrees with this one, this one wins.

---

## 1. Submission unit

**One archive = one event x one model, with optional configuration and ensemble member.**

A participant who runs three events with one configuration submits three
archives. A participant who runs the same event with two different
configurations submits two archives for that event, distinguished by the
configuration identifier.

The rationale is validation and resubmission cost: a single all-events package
would be ~15 GB and would have to be rebuilt and re-uploaded in full if one file
failed validation. Per-event packages are ~2-4 GB.

The portal's database upload ID remains the authoritative unique identifier for
a submission. The archive name is for human legibility and for machine
extraction of the configuration identity.

## 2. Archive name

```
<INSTITUTE>-<MODEL>-<EVENT>-<POC>[-CONFIG<NN>][-MEM<NN>].tar.gz
```

Example:

```
HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz
```

| Token | Meaning | Charset |
|---|---|---|
| `INSTITUTE` | Institution short code | `[A-Z0-9]+` |
| `MODEL` | Model identifier | `[A-Z0-9]+` |
| `EVENT` | Event code from section 3 | fixed list |
| `POC` | Surname of the point of contact | `[A-Z0-9]+` |
| `CONFIG<NN>` | Optional configuration identifier, such as `CONFIG01` | `CONFIG[0-9]{2,}` |
| `MEM<NN>` | Optional ensemble member, such as `MEM01` | `MEM[0-9]{2,}` |

Accepted extensions: `.tar.gz`, `.zip`. When both optional suffixes are used,
`CONFIG<NN>` comes before `MEM<NN>`.

**Tokens must not contain hyphens**, because the hyphen is the field separator.
A model whose name contains a hyphen or a space is written without it:
`WRF-ARW` becomes `WRFARW`. This matches the existing rule for NetCDF filenames.

The portal supports explicit replacement, which marks the previous submission
`superseded` rather than deleting it.

## 3. Events

| Event code | Name | Category | Baseline period (UTC) | Peak impact period (UTC) |
|---|---|---|---|---|
| `MANGKHUT2018` | Typhoon Mangkhut (2018) | Tropical cyclone | 2018-09-15 00Z to 2018-09-17 00Z | 2018-09-16 00Z to 2018-09-16 12Z |
| `HRAIN2023` | Black Rainstorm (2023) | Heavy rain | 2023-09-06 00Z to 2023-09-09 00Z | 2023-09-07 14Z to 2023-09-08 08Z |
| `HRAIN2025` | Black Rainstorm (2025) | Heavy rain | 2025-08-03 00Z to 2025-08-06 00Z | 2025-08-04 21Z to 2025-08-05 12Z |
| `HEAT2022` | Heatwave (2022) | Extreme heat | 2022-07-22 00Z to 2022-07-25 00Z | 2022-07-23 00Z to 2022-07-24 12Z |
| `HEAT2024` | Heatwave (2024) | Extreme heat | 2024-08-27 00Z to 2024-08-29 00Z | 2024-08-28 00Z to 2024-08-28 12Z |

## 4. Directory structure

```
HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz
`-- HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01/     <- top directory == archive name without extension
    |-- Participant_Model_Documentation.pdf
    |-- rumi_manifest.json                          <- written by rumi_validate.py, optional
    |
    |-- ERA5-AN/
    |   `-- Init-0/
    |       |-- ERA5-AN-MPAS-HRAIN2025-20250803000000.nc
    |       `-- ...
    |
    `-- GFS-FC/
        |-- Init-5/
        |-- Init-4/
        |-- Init-3/
        |-- Init-2/
        |-- Init-1/
        |-- Init-0.5/
        `-- Init-0.25/
```

Rules:

1. Exactly one top-level directory, named identically to the archive with the
   extension removed.
2. Every `.nc` file sits at exactly `<top>/<EXPERIMENT>/<INIT>/<file>.nc`.
   No deeper nesting, no NetCDF files at other levels.
3. Participants include **only** the experiments and initialization runs they
   actually completed. Empty directories are not required and not expected.
4. `Participant_Model_Documentation.pdf` (or `.docx`) at the top level is
   required.

## 5. Experiment directories

Directory names are the canonical RUMI experiment identifiers already used in
NetCDF filenames and in the `experiment` global attribute. The reversed forms
(`AN-ERA5`, `FC-GFS`) are **not** used, so no mapping has to be maintained.

| Analysis-driven | Forecast-driven |
|---|---|
| `ERA5-AN` | `GFS-FC` |
| `FNL-AN` | `UKMO-FC` |
| `JRA55-AN` | `OTHER-FC` |
| `UKMO-AN` | |
| `OTHER-AN` | |

The `experiment` global attribute of every file inside a directory must equal
that directory's name.

## 6. Initialization directories

The `Init-*` labels from the intercomparison guidelines are retained. They are
**labels, not offsets**: `Init-1` does not mean "24 hours before the peak". For
events whose peak impact does not begin at 00 UTC, the longer-lead runs use the
00 UTC forecast cycle, so the actual offset varies. For example, `Init-1` for
HRAIN2023 is 38 hours before the peak impact start, not 24.

The actual initialization time is always recorded in the NetCDF metadata; the
directory name is only an index into the table below.

### Event-specific initialization times (UTC)

| Event | Init-5 | Init-4 | Init-3 | Init-2 | Init-1 | Init-0.5 | Init-0.25 |
|---|---|---|---|---|---|---|---|
| `MANGKHUT2018` | Sep 11 00Z | Sep 12 00Z | Sep 13 00Z | Sep 14 00Z | Sep 15 00Z | Sep 15 12Z | Sep 15 18Z |
| `HRAIN2023` | Sep 02 00Z | Sep 03 00Z | Sep 04 00Z | Sep 05 00Z | Sep 06 00Z | Sep 07 02Z | Sep 07 08Z |
| `HRAIN2025` | Jul 30 00Z | Jul 31 00Z | Aug 01 00Z | Aug 02 00Z | Aug 03 00Z | Aug 04 09Z | Aug 04 15Z |
| `HEAT2022` | Jul 18 00Z | Jul 19 00Z | Jul 20 00Z | Jul 21 00Z | Jul 22 00Z | Jul 22 12Z | Jul 22 18Z |
| `HEAT2024` | Aug 23 00Z | Aug 24 00Z | Aug 25 00Z | Aug 26 00Z | Aug 27 00Z | Aug 27 12Z | Aug 27 18Z |

`Init-5` through `Init-1` are taken verbatim from the guidelines. `Init-0.5` and
`Init-0.25` are defined as peak impact start minus 12 hours and minus 6 hours
respectively, which reproduces the HRAIN2023 values (Sep 07 02Z, Sep 07 08Z)
already circulated.

### Analysis-driven experiments

| Case | Directory | Meaning |
|---|---|---|
| One AN initialization (the normal case) | `Init-0` | The participant's single analysis-driven run. Its `initialization_time` attribute is authoritative. |
| Several AN initializations for one event | `Init-<YYYYMMDDHH>` | Absolute UTC initialization time, e.g. `Init-2025080300`. |

Keeping an `Init-*` level for AN rather than omitting it means the hierarchy is
identical for AN and FC, and it gives multiple AN initializations a place to live
without special cases.

## 7. Required submission period

Two resolution categories, derived from the `horizontal_resolution` global
attribute: **~1 km** (>= 1000 m) and **sub-km** (< 1000 m).

| Event | ~1 km required period | Sub-km required period | Output interval | Final timestamp |
|---|---|---|---|---|
| `MANGKHUT2018` | Sep 15 00Z - Sep 17 00Z | Sep 16 00Z - Sep 17 00Z | 1 h | required |
| `HRAIN2023` | Sep 06 00Z - Sep 09 00Z | Sep 07 14Z - Sep 08 20Z | 1 h | required |
| `HRAIN2025` | Aug 03 00Z - Aug 06 00Z | Aug 04 21Z - Aug 06 00Z | 1 h | required |
| `HEAT2022` | Jul 22 00Z - Jul 25 00Z | Jul 23 00Z - Jul 25 00Z | 1 h | required |
| `HEAT2024` | Aug 27 00Z - Aug 29 00Z | Aug 28 00Z - Aug 29 00Z | 1 h | required |

The ~1 km column is the baseline simulation period from the guidelines. The
sub-km required period starts at the event's peak impact start and ends 12
hours after the peak impact end. Any spin-up a sub-km run needs before the
peak impact start is a modeling choice left to each participant; it is not
part of the required submission window and is not itself validated.

**Staggered forecast runs.** If the actual initialization time is later than the
required start above, the required period for that run begins at the actual
initialization time. The required final timestamp is unchanged. For example, the
HRAIN2025 `Init-0.25` run initialized at Aug 04 15Z is required to cover
Aug 04 15Z to Aug 06 00Z (34 hourly files), not Aug 03 00Z to Aug 06 00Z.

**Only the final timestamp is a hard requirement.** The initial timestamp is not
required, because accumulated fields such as hourly rainfall are not meaningful
at the first output step. Missing initial timestamps and gaps inside the series
are reported as warnings so they can be discussed, not rejected automatically.

## 8. File format

The grid, encoding, and filename convention are unchanged from the current
protocol; the required variable list is expanded in this version (see below).
See `README.md` for the full grid and variable specification.

| Property | Value |
|---|---|
| Format | NetCDF4, zlib compressed |
| Conventions | CF-1.8 |
| Grid | 9.7 arc-second regular lat/lon, 234 lon x 171 lat, core domain only |
| First lat/lon | 22.12 N, 113.82 E |
| Time | one timestamp per file, UTC |
| Missing value | `-9999.0` |
| Filename | `<experiment>-<Model>-<Event>-<YYYYMMDDHHMMSS>[_<member>][_rNN].nc` |

### Required variables

Three groups, defined in `portal/backend/rumi_protocol.py` and enforced
identically by the portal and by `rumi_validate.py`. See `README.md` for
units and descriptions.

**Required 2D core — missing rejects the file:**
`T2M` `U10M` `V10M` `PRATE` `SLP` `RH2M` `TOTAL_PRECIP` `PSFC` `Q2M`

**Recommended radiation 2D — missing is accepted, but is reported to the uploader:**
`SWDOWN` `SWNET` `SWDIR` `LWDOWN` `LWNET`

This group comes from guideline sections 7.1 / 7.4.2. It is recommended
rather than required: a submission missing one or more of these variables is
accepted, and the upload receipt lists exactly which ones were not found so
they can be added in a later version if the model produces them.

**Recommended 3D on the 850, 500, and 200 hPa levels — missing is accepted, but is reported to the uploader:**
`T` `Z` `RH` `U` `V` `Q`, plus one of `OMEGA` or `W`. Vertical motion may be
supplied as pressure velocity or geometric velocity; either satisfies the
recommendation. As with radiation, a submission missing one or more of these
is accepted, and the missing variables are reported to the uploader.

Required global attributes: `Conventions`, `title`, `institution`, `source`,
`history`, `experiment`, `event`, `event_name`, `simulation_start_time`,
`initialization_time`, `forecast_initialization_time`,
`forecast_lead_time_hours`, `forcing_mode`, `forcing_source`, `forcing_data`,
`forcing_data_version`, `forcing_resolution`, `forcing_update_interval`,
`horizontal_resolution`, `contact`, `creator_name`, `creation_date`, `version`.

`horizontal_resolution` is load-bearing in v3: it selects the required period
column in section 7. Write it as `"1 km"`, `"500 m"`, `"0.5 km"` and so on.

## 9. Validation rules

The portal and `rumi_validate.py` apply the same rules from the same
`RULES_VERSION`. Errors block acceptance; warnings do not.

### Errors

| Check | Rule |
|---|---|
| Archive name | Must match section 2 |
| Top directory | Exactly one, equal to the archive stem |
| NetCDF placement | Exactly `<top>/<EXPERIMENT>/<INIT>/x.nc` |
| Experiment directory | Must be a canonical identifier from section 5 |
| Init directory | Must match section 6 |
| Filename consistency | Filename experiment / model / event must match the directory experiment, archive model, archive event |
| One event per archive | All files must belong to the archive's event |
| Documentation | A `.pdf` or `.docx` must be present at the top level |
| Final timestamp | The required final timestamp of section 7 must be present in every Init directory |
| Duplicate timestamps | Two files with the same timestamp in one Init directory |
| FC initialization | `forecast_initialization_time` more than 6 h from the tabled value for that `Init-*` label, except `Init-0.5` / `Init-0.25` (provisional, see Warnings) |
| AN `Init-0` | `initialization_time` not identical across all files in the directory |
| AN `Init-<stamp>` | `initialization_time` not equal to the directory's timestamp |
| Grid | Dimensions, coordinates, and core 2D variables, as today |
| Archive safety | Absolute paths or `..` components |

### Warnings

| Check | Rule |
|---|---|
| Initial timestamp | Required start of section 7 absent |
| Continuity | Gaps in the hourly series (up to 10 listed, plus a total) |
| FC initialization | Within 6 h of the tabled value but not exact, i.e. snapped to an available forecast cycle |
| FC initialization (`Init-0.5` / `Init-0.25`, provisional) | `forecast_initialization_time` more than 6 h from the tabled value for these two labels only; not rejected while their feasibility on standard GFS cycles is unconfirmed |
| Radiation variables (recommended) | A recommended radiation 2D variable (`SWDOWN`, `SWNET`, `SWDIR`, `LWDOWN`, `LWNET`) is missing; the submission is accepted and the missing variables are listed for the uploader |
| 3D variables (recommended) | A recommended 3D variable (`T`, `Z`, `RH`, `U`, `V`, `Q`) is missing on the 850/500/200 hPa levels, or both `OMEGA` and `W` are missing; the submission is accepted and the missing variables are listed for the uploader |
| Resolution | `horizontal_resolution` unparseable; the ~1 km column is assumed |
| Metadata | Missing recommended global or physics attributes |
| Manifest | `rumi_manifest.json` written by a different `RULES_VERSION` |

## 10. Open items

These need group confirmation before the participant instructions are final.

1. **Init-0.5 / Init-0.25 for forecast-driven runs.** For HRAIN2023 the tabled
   times are 02Z and 08Z, and for HRAIN2025 they are 09Z and 15Z. These are not
   standard 6-hourly GFS cycles. This specification accepts an initialization
   snapped to the nearest available cycle within 6 hours and, beyond that,
   reports a warning rather than an error for these two labels only (section 9).
   Still to be confirmed with Lewis: whether these fractional-lead labels are
   workable at all given GFS only publishes standard forecast cycles.
2. **Storage.** 17 institutions x 5 events x ~3 GB is approximately 255 GB for a
   single configuration each. The portal filesystem has 4.9 TB free, so this is
   comfortable even with resubmissions and multiple configurations.

## 11. Portal behaviour that participants should know

- Uploads are chunked and **resumable**. An interrupted upload can be continued
  rather than restarted.
- A per-event archive contains several hundred NetCDF files. Validation takes a
  few minutes and runs **asynchronously**: the upload returns immediately with
  status `queued`, and the page shows validation progress. Closing the browser
  does not cancel it.
- Structural problems (naming, directory layout) are reported within seconds,
  before any per-file work begins.
- After an archive passes validation, the original archive is retained as the
  immutable source of truth. The server then creates a private analysis copy
  and a server-generated manifest; the Submissions view reports whether that
  copy is `queued`, `extracting`, `ready`, or `failed`.
- Running `rumi_validate.py` locally before packaging avoids nearly all of this
  round trip.
