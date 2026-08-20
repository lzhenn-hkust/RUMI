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

### 3D Pressure-Level Variables

The 3D fields are recommended for archiving but are not required by the current
portal. The authoritative example defines 850, 500, and 200 hPa.

| Variable | Description | Units |
|----------|-------------|-------|
| T | Air temperature | K |
| Z | Geopotential height | m |
| RH | Relative humidity | 0-1 |
| U | Eastward wind | m s-1 |
| V | Northward wind | m s-1 |
| OMEGA | Vertical velocity | Pa s-1 |

Additional 2D and 3D fields are defined in `create_ncdf.py`.

## File Convention

- Format: NetCDF4
- Conventions: CF-1.8
- Time: one timestamp per file, expressed in UTC
- Compression: zlib
- Missing value: `-9999.0`

### Filename

```text
<RUMI experiment>-<Model>-<Event>-<YYYYMMDDHHMMSS>[_<member>][_vNN].nc
```

The experiment is the complete forcing and mode tag. `AN` means
analysis/reanalysis driven, while `FC` means forecast driven.

```text
RUMI-ERA5-AN-WRF-MANGKHUT2018-20180916120000.nc
RUMI-GFS-FC-MPAS-HRAIN2025-20250804000000.nc
```

For the second example:

- `experiment = RUMI-GFS-FC`
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

Participants upload one `.zip` or `.tar.gz` structured archive for an event.
The archive filename must contain only the institution, model, event, and point
of contact. Configuration and revision details belong in
`Participant_Model_Documentation.pdf`.

```text
HKUST-MPAS-HRAIN2025-SHI.tar.gz
`-- HKUST-MPAS-HRAIN2025-SHI/
    |-- Participant_Model_Documentation.pdf
    |-- ERA5-AN/
    |   `-- Init-*/
    `-- GFS-FC/
        `-- Init-*/
```

Each NetCDF member is checked with the portal's shared NetCDF validator.
Archive acceptance is all-or-nothing. Time fields and model
configuration details are read from the NetCDF global attributes and the
participant documentation, so they do not need to be entered in the upload
form.

## Portal Storage Organization

Accepted uploads are indexed in SQLite and stored privately under the following
directory structure:

```text
submissions/<institution>/<experiment>/<model>/<event>/<upload_id>_<file-name>
```

Institution, experiment, model, and event make the files easy to browse and
batch-process, while the upload ID prevents filename collisions. Institution
is also stored as a snapshot on each upload record, so changing a user's
profile later does not change the historical attribution or storage location.
Older submissions retain their original storage paths and remain accessible
through the database index.
