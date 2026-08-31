# RUMI Phase 1 Output Protocol

This repository contains the Phase 1 Hong Kong core-domain output specification,
the NetCDF creation script, and the RUMI upload portal.

## Standard Core Grid

All 2D submissions must be interpolated to the following regular
latitude/longitude grid. The portal accepts the core domain only.

| Property | Value |
|----------|-------|
| Resolution | 9.7 arc-seconds (~0.002694 degrees, ~300 m) |
| Latitude points | 171 |
| Longitude points | 234 |
| First latitude | 22.12 degrees N |
| First longitude | 113.82 degrees E |
| Last latitude | 22.57805556 degrees N |
| Last longitude | 114.44780556 degrees E |
| Total cells | 40,014 |

Coordinates are defined exactly as:

```text
lat[i] = 22.12  + i * (9.7 / 3600), i = 0 ... 170
lon[j] = 113.82 + j * (9.7 / 3600), j = 0 ... 233
```

The expanded RUMI domain is not accepted by the Phase 1 upload portal.

## Output Variables

### Core 2D Variables

Every submitted NetCDF file must contain all nine variables.

| Variable | Description | Units |
|----------|-------------|-------|
| T2M | 2-m air temperature | K |
| U10M | 10-m eastward wind | m s-1 |
| V10M | 10-m northward wind | m s-1 |
| PRATE | Precipitation rate | kg m-2 s-1 |
| SLP | Mean sea-level pressure | Pa |
| RH2M | 2-m relative humidity | 0-1 |
| TOTAL_PRECIP | Accumulated total precipitation | kg m-2 |
| PSFC | Surface pressure | Pa |
| Q2M | 2-m specific humidity | kg kg-1 |

### Radiation 2D Variables (recommended)

These five radiation variables are **recommended**, not required: a
submission missing one or more of them is still accepted, and the upload
receipt lists exactly which ones were not found.

| Variable | Description | Units |
|----------|-------------|-------|
| SWDOWN | Downward shortwave radiation | W m-2 |
| SWNET | Net shortwave radiation | W m-2 |
| SWDIR | Direct shortwave radiation | W m-2 |
| LWDOWN | Downward longwave radiation | W m-2 |
| LWNET | Net longwave radiation | W m-2 |

### 3D Pressure-Level Variables (recommended)

The 3D fields at the 850, 500, and 200 hPa levels are **recommended**, not
required: `T`, `Z`, `RH`, `U`, `V`, `Q`, plus at least one of `OMEGA` or `W`
for vertical motion (pressure velocity or geometric velocity; either counts).
A submission missing one or more of these is still accepted, and the upload
receipt lists exactly which ones were not found.

| Variable | Description | Units |
|----------|-------------|-------|
| T | Air temperature | K |
| Z | Geopotential height | m |
| RH | Relative humidity | 0-1 |
| U | Eastward wind | m s-1 |
| V | Northward wind | m s-1 |
| Q | Specific humidity | kg kg-1 |
| OMEGA | Vertical velocity (pressure) | Pa s-1 |
| W | Vertical velocity (geometric) | m s-1 |

Additional 2D and 3D fields are defined in `create_ncdf.py`.

## File Convention

- Format: NetCDF4
- Conventions: CF-1.8
- Time: one timestamp per file, expressed in UTC
- Compression: zlib
- Missing value: `-9999.0`

### Filename

```text
<experiment>-<Model>-<Event>-<YYYYMMDDHHMMSS>[_<member>][_rNN].nc
```

The experiment is the complete forcing and mode tag. `AN` means
analysis/reanalysis driven, while `FC` means forecast driven.

```text
ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc
GFS-FC-MPAS-HRAIN2025-20250804000000.nc
```

For the second example:

- `experiment = GFS-FC`
- `model = MPAS`
- `event = HRAIN2025`

The model identifier is the final hyphen-delimited token before the event code.
Use an identifier without hyphens, such as `WRFARW`, when a model name contains
multiple words.

### Required Metadata

The global `experiment` attribute must exactly match the complete experiment
tag in the filename. The global `source` attribute identifies the model.
Files should also document:

- simulation and initialization times
- forecast initialization and lead time
- forcing mode, source, dataset, version, resolution, and update interval
- model horizontal and vertical configuration
- contact and creation information
- physics parameterizations and surface datasets

See `set_info()` in `create_ncdf.py` for the complete metadata structure.

## Usage

Generate a populated example file:

```bash
python3 create_ncdf.py
```

Generate a core-only 2D template:

```bash
python3 create_ncdf.py --template RUMI_template_2d.nc
```

For model output, update `set_info()` and replace the synthetic data logic in
`fill_example_data()` with data read and interpolated from the source model.

The portal validates the filename interpretation, all core variables, NetCDF4
format, exact 234 x 171 dimensions, and every latitude/longitude coordinate
before accepting a submission.

## Structured Archives

Phase 1 submissions are uploaded as one archive per event. The authoritative
specification is [docs/RUMI-submission-spec-v3.md](docs/RUMI-submission-spec-v3.md)
(`RULES_VERSION: 2026-08-rumi-v3.2`); the text below is a summary.

```text
HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01.tar.gz
`-- HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01/
    |-- Participant_Model_Documentation.pdf
    |-- rumi_manifest.json          (written by rumi_validate.py, optional)
    |-- ERA5-AN/
    |   `-- Init-0/
    `-- GFS-FC/
        |-- Init-5/ ... `-- Init-0.25/
```

- The archive name is `<INSTITUTE>-<MODEL>-<EVENT>-<POC>[-CONFIG<NN>][-MEM<NN>]`
  with `.tar.gz` or `.zip`. Configuration and ensemble member suffixes are
  optional and appear in that order. Fields are uppercase letters and digits and
  contain no hyphens, so `WRF-ARW` is written `WRFARW`.
- Every NetCDF file sits at `<archive>/<EXPERIMENT>/<Init-*>/<file>.nc`.
  Experiment directories use the canonical identifiers (`ERA5-AN`,
  `GFS-FC`), never the reversed forms.
- `Init-*` labels index an event-specific table of initialization times; they
  are labels, not offsets. Analysis-driven runs use `Init-0`, or
  `Init-<YYYYMMDDHH>` when there are several.
- The required final timestamp of the submission period must be present. A
  missing first timestamp or a gap in the hourly series is reported as a
  warning, not a rejection.

### Check before you upload

`rumi_validate.py`, downloadable from the portal, applies the same rules from
the same `RULES_VERSION` as the portal itself:

```bash
python3 rumi_validate.py HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01/
python3 rumi_validate.py --write-manifest HKUST-MPAS-HRAIN2025-LIU-CONFIG01-MEM01/
```

It is generated from `portal/backend/rumi_protocol.py` by
`python3 tools/build_validator.py`, so the two cannot drift apart; the test
suite fails if the committed copy is stale.

An archive holds several hundred files, so the portal validates it in the
background: the upload returns immediately with status `queued` and the page
shows progress. Structural problems are reported within seconds, before any
per-file work starts.

## Portal Storage Organization

Accepted uploads are indexed in SQLite and stored privately under the following
directory structure:

```text
single files: submissions/<institution>/<experiment>/<model>/<event>/<upload_id>_<file-name>
archives:     submissions/<institution>/<event>/<model>/<upload_id>_<archive-name>
analysis:     extracted/<institution>/<event>/<model>/<upload_id>/<archive contents>
manifests:    manifests/<institution>/<event>/<model>/<upload_id>.json
```

An event archive spans several experiments, so it cannot be filed under one of
them; it is filed by event and model instead.

Institution, experiment, model, and event make the files easy to browse and
batch-process, while the upload ID prevents filename collisions. Institution
is also stored as a snapshot on each upload record, so changing a user's
profile later does not change the historical attribution or storage location.
Older submissions retain their original storage paths and remain accessible
through the database index.

The uploaded archive is the immutable source of truth. After a successful
archive validation, the background worker creates a private, independently
indexed analysis copy under `extracted/` and writes a server-generated manifest
under `manifests/`. Extraction is staged and checks member paths, links,
duplicates, and expanded size before the derived copy becomes visible. The
database records `extraction_status` (`queued`, `extracting`, `ready`, or
`failed`) plus the derived paths and file counts; a failed extraction never
removes the accepted original archive.
