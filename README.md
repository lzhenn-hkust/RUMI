# RUMI — Standard Output Grid

## Grid Specification

All participating models must interpolate their output onto the following unified standard grid for intercomparison:

| Property | Value |
|----------|-------|
| Type | Regular latitude/longitude |
| Resolution | 15 arc-seconds (~0.004167°, ~460 m) |
| Latitude range | 22.12°N – 22.58°N |
| Longitude range | 113.82°E – 114.45°E |
| Grid dimensions | 152 (lon) × 111 (lat) |
| Coverage | Hong Kong and surrounding waters |

## Output Variables

### Core 2D Variables (Mandatory)

| Variable | Description | Units |
|----------|-------------|-------|
| T2M | 2-m air temperature | K |
| U10M | 10-m eastward wind | m/s |
| V10M | 10-m northward wind | m/s |
| PRATE | Precipitation rate | kg m⁻² s⁻¹ |
| SLP | Mean sea level pressure | Pa |
| RH2M | 2-m relative humidity | 0–1 |
| TOTAL_PRECIP | Accumulated total precipitation | kg m⁻² |
| PSFC | Surface pressure | Pa |
| Q2M | 2-m specific humidity | kg/kg |

### 3D Pressure-Level Variables (Mandatory)

18 standard pressure levels: 1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50 hPa

| Variable | Description | Units |
|----------|-------------|-------|
| T | Air temperature | K |
| Z | Geopotential height | m |
| RH | Relative humidity | 0–1 |
| U | Eastward wind | m/s |
| V | Northward wind | m/s |
| OMEGA | Vertical velocity | Pa/s |

### Recommended Variables

Additional surface variables (TSK, TD2M, LH, HFX, radiation fluxes, etc.) and 3D variables (THETA, Q, W, QC, QI, QR, TKE) are recommended but not required. See `create_ncdf.py` for the full list.

## File Format

- **Format**: NetCDF4, CF-1.8 conventions
- **Time**: One timestamp per file, seconds since 1970-01-01 UTC
- **Compression**: zlib enabled
- **Missing value**: -9999.0

### Filename Convention

```
RUMI-{forcing}-{model}-{event}-{YYYYMMDDHHmmss}.nc
```

Example: `RUMI-ERA5-WRF-MANGKHUT2018-20180916120000.nc`

## Usage

Use `create_ncdf.py` to generate compliant output files:

```bash
# Generate an example file with placeholder data
python3 create_ncdf.py

# To use with your model output:
# 1. Update set_info() with your experiment metadata
# 2. Modify get_model_data() to read your model output
# 3. Run the script
```

A template file `RUMI_template_2d.nc` is also provided for reference.
