# RUMI — Regional Urban Model Intercomparison

## Overview

RUMI is a multi-phase international initiative to evaluate the performance of numerical models in predicting urban extreme weather events in coastal cities. **Phase 1** focuses on **Hong Kong**, leveraging its dense observational network, complex terrain, and frequent exposure to tropical cyclones, heavy rainfall, and extreme heat.

The intercomparison welcomes regional NWP models (e.g., WRF, MPAS, UM, RAMS, ARPS) as well as AI-based weather prediction models.

## Phase 1 Events

| ID | Event | Period |
|----|-------|--------|
| MANGKHUT2018 | Typhoon Mangkhut | Sep 2018 |
| HRAIN2023 | Black Rainstorm | Sep 2023 |
| HRAIN2025 | Black Rainstorm | Aug 2025 |
| HEAT2022 | Extreme Heat | Jul 2022 |
| HEAT2024 | Extreme Heat | Aug 2024 |

Participants may choose any subset of events. Running all five is encouraged but not required.

## Experiments

- **RUMI-ERA5** (recommended): reanalysis-driven using ECMWF ERA5
- **RUMI-FNL** (optional): reanalysis-driven using NCEP FNL (1999+)
- **RUMI-GFS** (optional): forecast-driven using NCEP GFS (2010+)
- **RUMI-OTHER** (optional): other reanalysis/analysis products

## Output Specifications

- **Format**: NetCDF4, CF-1.8 conventions
- **Standard grid**: 15 arc-second regular lat/lon over Hong Kong
- Use `create_ncdf.py` as the reference script for generating compliant output files
- A template file `RUMI_template_2d.nc` is provided for reference

## Repository Contents

```
├── Intercomparison-Guidelines_ZhenningLI_260401.docx   # Full protocol document
├── create_ncdf.py                                       # NetCDF creation reference script
├── RUMI_template_2d.nc                                  # Template output file
└── README.md
```

## How to Participate

1. Check if your model can produce the required output variables over the Hong Kong domain
2. Select at least one event from the table above
3. Set up simulations following the guidelines document (recommended resolution: 1 km or finer)
4. Format output using the provided `create_ncdf.py` script
5. Contact the RUMI coordination team to register and submit data

## Contact

For questions or to register participation, please contact the RUMI organizing team.

**Authors**: Zhenning LI, Xiaoming SHI, Chi Ming SHUM, Lewis BLUNN, Zhuo LIU, Jimmy Fung, Alexis Lau, and Fei Chen
