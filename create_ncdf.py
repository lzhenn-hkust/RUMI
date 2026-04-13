#!/usr/bin/env python3
'''
RUMI (Regional Urban Model Intercomparison) NetCDF creation script.
Phase 1: Hong Kong

This script creates a properly formatted NetCDF4 output file conforming to
the RUMI protocol specifications. It demonstrates:
  - The standard output grid (15 arc-second regular lat/lon over Hong Kong)
  - Required variable names, attributes, and metadata structure
  - Correct handling of coordinate systems, time encoding, and CF conventions

Adapted from the Urban-PLUMBER benchmarking project (Mathew Lipson, UNSW).

Usage:
  Run "as-is" to generate an example NetCDF file with placeholder data:
      python3 create_ncdf.py

  To use with your own model output:
      1. Update set_info() with your model/experiment details
      2. Modify get_model_data() to read your model output
      3. Run the script

Changelog:
  v2.0 (2026-03-30): Complete rewrite for RUMI protocol. 2D gridded output
                      on standard 15 arc-sec lat/lon grid. Single-frame files.
'''

__title__   = 'RUMI NetCDF creation script'
__version__ = 'v2.0 (2026-03-30)'
__author__  = 'Zhenning LI'

import numpy as np
import netCDF4 as nc
from datetime import datetime, timezone

MISSING_FLOAT = np.float32(-9999.0)

# ============================================================================
# Standard Output Grid Definition
# ============================================================================
GRID = {
    'lat_south': 22.12,
    'lat_north': 22.58,
    'lon_west':  113.82,
    'lon_east':  114.45,
    'resolution_arcsec': 15,  # 15 arc-seconds ≈ 0.004167°
}
GRID['dlat'] = GRID['resolution_arcsec'] / 3600.0
GRID['dlon'] = GRID['resolution_arcsec'] / 3600.0
GRID['lats'] = np.arange(GRID['lat_south'], GRID['lat_north'], GRID['dlat'])
GRID['lons'] = np.arange(GRID['lon_west'],  GRID['lon_east'],  GRID['dlon'])
GRID['nlat'] = len(GRID['lats'])  # 111
GRID['nlon'] = len(GRID['lons'])  # 152

# Standard pressure levels (Pa) for 3D output
PRESSURE_LEVELS = np.array([
    100000, 97500, 95000, 92500, 90000, 85000, 80000, 70000,
    60000, 50000, 40000, 30000, 25000, 20000, 15000, 10000, 7000, 5000
], dtype=np.float32)

# ============================================================================
# Variable Definitions
# ============================================================================
# Format: (var_name, standard_name, long_name, units, extra_attrs)

CORE_2D_VARS = [
    ('T2M',         'air_temperature',                 '2-meter air temperature',                         'K',          {'height': '2 m'}),
    ('U10M',        'eastward_wind',                   '10-meter eastward wind component',                'm s-1',      {'height': '10 m'}),
    ('V10M',        'northward_wind',                  '10-meter northward wind component',               'm s-1',      {'height': '10 m'}),
    ('PRATE',       'precipitation_flux',              'Precipitation rate (liquid equivalent)',           'kg m-2 s-1', {}),
    ('SLP',         'air_pressure_at_mean_sea_level',  'Mean sea level pressure',                          'Pa',         {}),
    ('RH2M',        'relative_humidity',               '2-meter relative humidity (fraction 0-1)',         '1',          {'height': '2 m', 'valid_range': np.array([0.0, 1.0], dtype='f4')}),
    ('TOTAL_PRECIP','precipitation_amount',            'Accumulated total precipitation since sim start',  'kg m-2',     {'cell_methods': 'time: sum', 'accumulation_reference': 'simulation_start'}),
    ('PSFC',        'surface_air_pressure',            'Surface atmospheric pressure',                     'Pa',         {}),
    ('Q2M',         'specific_humidity',               '2-meter specific humidity',                        'kg kg-1',    {'height': '2 m'}),
    ('CWP',         'atmosphere_cloud_liquid_water_content','Column-integrated cloud liquid water path',   'kg m-2',     {}),
    ('IWP',         'atmosphere_cloud_ice_content',     'Column-integrated cloud ice water path',          'kg m-2',     {}),
    ('RWP',         'atmosphere_mass_content_of_rain',  'Column-integrated cloud rain water path',         'kg m-2',     {}),
    ('PW',          'atmosphere_water_vapor_content',   'Precipitable water (total column water vapor)',   'kg m-2',     {}),
]

RECOMMENDED_2D_SURFACE_VARS = [
    ('TSK',     'surface_temperature',                       'Surface skin temperature',                        'K',     {}),
    ('TD2M',    'dew_point_temperature',                     '2-meter dewpoint temperature',                    'K',     {'height': '2 m'}),
    ('LH',      'surface_upward_latent_heat_flux',           'Surface latent heat flux (positive upward)',       'W m-2', {'cell_methods': 'time: mean'}),
    ('HFX',     'surface_upward_sensible_heat_flux',         'Surface sensible heat flux (positive upward)',     'W m-2', {'cell_methods': 'time: mean'}),
    ('SWDOWN',  'surface_downwelling_shortwave_flux_in_air', 'Downward shortwave radiation at surface',         'W m-2', {'cell_methods': 'time: mean'}),
    ('SWUP',    'surface_upwelling_shortwave_flux_in_air',   'Upward shortwave radiation at surface',           'W m-2', {'cell_methods': 'time: mean'}),
    ('LWDOWN',  'surface_downwelling_longwave_flux_in_air',  'Downward longwave radiation at surface',          'W m-2', {'cell_methods': 'time: mean'}),
    ('LWUP',    'surface_upwelling_longwave_flux_in_air',    'Upward longwave radiation at surface',            'W m-2', {'cell_methods': 'time: mean'}),
    ('GRDFLX',  'downward_heat_flux_at_ground_level_in_soil','Ground heat flux (positive downward)',            'W m-2', {'cell_methods': 'time: mean'}),
    ('WSPD10M', 'wind_speed',                                '10-meter wind speed',                             'm s-1', {'height': '10 m'}),
    ('WDIR10M', 'wind_from_direction',                       '10-meter wind direction (meteorological)',        'degree', {'height': '10 m'}),
]

RECOMMENDED_2D_DIAG_VARS = [
    ('CLDFRAC',     'cloud_area_fraction',                                  'Total cloud fraction (0-1)',                          '1',          {}),
    ('CTH',         'cloud_top_altitude',                                   'Cloud top height above sea level',                    'm',          {}),
    ('CBH',         'cloud_base_altitude',                                  'Cloud base height above sea level',                   'm',          {}),
    ('HOURLY_PRECIP','precipitation_amount',                                'Hourly accumulated precipitation',                    'kg m-2',     {'cell_methods': 'time: sum', 'accumulation_interval': '1 hour'}),
    ('PRATE_CONV',   'convective_precipitation_flux',                       'Precipitation rate from parameterized convective processes only',      'kg m-2 s-1',        {}),
    ('PRATE_GRID',   'stratiform_precipitation_flux',                       'Precipitation rate from grid-scale (explicit) processes only',         'kg m-2 s-1',        {}),
    ('REFL_COMP',   'equivalent_reflectivity_factor',                      'Column-maximum simulated radar reflectivity',                           'dBZ',               {}),
    ('REFL_2KM',    'equivalent_reflectivity_factor',                      'Simulated radar reflectivity at 2km altitude above sea level',          'dBZ',               {}),
    ('CAPE',        'atmosphere_convective_available_potential_energy',     'Convective Available Potential Energy',               'J kg-1',     {}),
    ('CIN',         'atmosphere_convective_inhibition',                     'Convective Inhibition',                               'J kg-1',     {}),
    ('PBLH',        'atmosphere_boundary_layer_thickness',                  'Planetary boundary layer height',                     'm',          {}),
    ('W850',        'lagrangian_tendency_of_air_pressure',                  'Vertical velocity (omega) at 850 hPa level',          'Pa s-1',     {}),
    ('W500',        'lagrangian_tendency_of_air_pressure',                  'Vertical velocity (omega) at 500 hPa level',          'Pa s-1',     {}),
    ('HELICITY',    '-',                  'Storm-relative helicity integrated over 0-3 km layer',          'm2 s-2',     {}),
    ('UH_MAX',      '-',                  'Maximum updraft helicity over output interval (2-5 km layer)',  'm2 s-2',     {}),
    # Tropical Cyclone Events (e.g., MANGKHUT2018)
    ('WSPD10MAX',   'wind_speed_of_gust',                                   'Maximum 10-m wind speed over output interval',        'm s-1',      {}),
    ('SLP_MIN',     'air_pressure_at_mean_sea_level',                       'Minimum sea level pressure in model domain',          'Pa',         {}),
    ('VORT850',     'atmosphere_relative_vorticity',                        'Vertical component of relative vorticity at 850 hPa', 's-1',        {}),
    ('VORT700',     'atmosphere_relative_vorticity',                        'Vertical component of relative vorticity at 700 hPa', 's-1',        {}),
    # Heavy Rain/Convective Events (e.g., HRAIN2023, HRAIN2025)
    ('PRATE_MAX',   'precipitation_flux',                                    'Maximum precipitation rate in model domain',         'kg m-2 s-1', {}),
    ('FLASH_RATE',  '',                                                      'Simulated lightning flash rate per hour (if available)', 'flashes hour-1', {}),
    ('IVT',         '',                                                      'Integrated water vapor transport magnitude',         'kg m-1 s-1', {}),
]

MANDATORY_3D_VARS = [
    ('T',     'air_temperature',                     'Air temperature on pressure levels',       'K',      {}),
    ('Z',     'geopotential_height',                 'Geopotential height on pressure levels',   'm',      {}),
    ('RH',    'relative_humidity',                   'Relative humidity on pressure levels',     '1',      {'valid_range': np.array([0.0, 1.0], dtype='f4')}),
    ('U',     'eastward_wind',                       'Eastward wind on pressure levels',         'm s-1',  {}),
    ('V',     'northward_wind',                      'Northward wind on pressure levels',        'm s-1',  {}),
    ('OMEGA', 'lagrangian_tendency_of_air_pressure', 'Vertical velocity on pressure levels',     'Pa s-1', {}),
    ('W',     'upward_air_velocity',                 'Vertical velocity in height levels',  'm s-1',   {}),
    ('Q',     'specific_humidity',                          'Specific humidity on pressure levels',       'kg kg-1', {}),
]

RECOMMENDED_3D_VARS = [
    ('THETA', 'air_potential_temperature',                  'Potential temperature on pressure levels',   'K',       {}),
    ('QC',    'mass_fraction_of_cloud_liquid_water_in_air', 'Cloud liquid water mixing ratio',            'kg kg-1', {}),
    ('QI',    'mass_fraction_of_cloud_ice_in_air',          'Cloud ice mixing ratio',                     'kg kg-1', {}),
    ('QR',    'mass_fraction_of_rain_in_air',               'Rain water mixing ratio',                    'kg kg-1', {}),
    ('TKE',   'specific_turbulent_kinetic_energy_of_air',   'Turbulent kinetic energy',                   'm2 s-2',  {}),
]

# ============================================================================
# Main Functions
# ============================================================================

def set_info():
    '''Set experiment metadata. Update this for your simulation.'''
    info = {
        # Experiment identification
        'experiment':       'RUMI-ERA5',
        'event':            'MANGKHUT2018',
        'event_name':       'Typhoon Mangkhut (2018)',
        'model':            'WRF',

        # Simulation timing (ISO 8601)
        'simulation_start_time':        '2018-09-15T00:00:00Z',
        'initialization_time':          '2018-09-15T00:00:00Z',
        'forecast_initialization_time': '2018-09-15T00:00:00Z',
        'forecast_lead_time_hours':     '0',

        # Forcing data
        'forcing_data':     'ECMWF ERA5',

        # Model configuration
        'horizontal_resolution': '1 km',
        'vertical_levels':       '50',
        'model_top_pressure':    '50 hPa',

        # Contact
        'institution':    'Hong Kong University of Science and Technology',
        'contact':        'your.email@institution.edu',
        'creator_name':   'Your Name',
        'creation_date':  datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'version':        'v01',

        # Physics parameterizations (update for your model)
        'microphysics_scheme':    'Morrison double-moment',
        'cumulus_scheme':         'None (explicit convection)',
        'pbl_scheme':             'MYNN Level 2.5',
        'radiation_scheme':       'RRTMG',
        'land_surface_scheme':    'Noah-MP',
        'urban_scheme':           'Single-layer UCM',
        'surface_layer_scheme':   'Monin-Obukhov similarity',
        'turbulence_closure':     'TKE-based (1.5-order)',
        'landuse_dataset':        'MODIS IGBP 21-category, 500 m',
        'urban_morphology_source':'WUDAPT LCZ + OpenStreetMap building data',
        'terrain_dataset':        'SRTM 90 m',
        'soil_dataset':           'FAO-UNESCO 16-category',

        # Output settings
        'outpath':    './output',
        'timestamp':  '20180916120000',  # example: 2018-09-16 12:00:00 UTC
    }

    # Construct filename following RUMI convention
    info['fname'] = (
        f"RUMI-{info['experiment'].split('-')[1]}-{info['model']}"
        f"-{info['event']}-{info['timestamp']}.nc"
    )

    return info


def create_rumi_netcdf(info, include_recommended=True, include_3d=True):
    '''Create a RUMI-compliant NetCDF4 file with all required structure.

    Parameters
    ----------
    info : dict
        Experiment metadata from set_info()
    include_recommended : bool
        Include recommended 2D variables (default True)
    include_3d : bool
        Include 3D pressure-level variables (default True)
    '''

    import os
    os.makedirs(info['outpath'], exist_ok=True)
    fpath = os.path.join(info['outpath'], info['fname'])

    nlat = GRID['nlat']
    nlon = GRID['nlon']
    npres = len(PRESSURE_LEVELS)

    # Parse timestamp for time coordinate
    ts = datetime.strptime(info['timestamp'], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    time_seconds = (ts - epoch).total_seconds()

    with nc.Dataset(fpath, mode='w', format='NETCDF4') as ds:

        # ---- Dimensions ----
        ds.createDimension('time', 1)
        ds.createDimension('nv', 2)
        ds.createDimension('lat', nlat)
        ds.createDimension('lon', nlon)
        if include_3d:
            ds.createDimension('pressure', npres)

        # ---- Time coordinate ----
        t = ds.createVariable('time', 'f8', ('time',))
        t.long_name     = 'time'
        t.standard_name = 'time'
        t.units         = 'seconds since 1970-01-01 00:00:00'
        t.calendar      = 'gregorian'
        t.axis          = 'T'
        t.bounds        = 'time_bnds'
        t[:] = time_seconds

        tb = ds.createVariable('time_bnds', 'f8', ('time', 'nv'))
        tb.long_name = 'time interval boundaries'
        tb[0, 0] = time_seconds - 3600  # 1-hour averaging window
        tb[0, 1] = time_seconds

        # ---- Spatial coordinates ----
        lat = ds.createVariable('lat', 'f8', ('lat',))
        lat.long_name     = 'latitude'
        lat.standard_name = 'latitude'
        lat.units         = 'degrees_north'
        lat.axis          = 'Y'
        lat[:] = GRID['lats']

        lon = ds.createVariable('lon', 'f8', ('lon',))
        lon.long_name     = 'longitude'
        lon.standard_name = 'longitude'
        lon.units         = 'degrees_east'
        lon.axis          = 'X'
        lon[:] = GRID['lons']

        # ---- Pressure levels (if 3D) ----
        if include_3d:
            p = ds.createVariable('pressure', 'f4', ('pressure',))
            p.long_name     = 'pressure'
            p.standard_name = 'air_pressure'
            p.units         = 'Pa'
            p.positive      = 'down'
            p.axis          = 'Z'
            p[:] = PRESSURE_LEVELS

        # ---- Surface fields (time-invariant) ----
        lm = ds.createVariable('LANDMASK', 'f4', ('lat', 'lon'),
                               fill_value=MISSING_FLOAT, zlib=True)
        lm.long_name     = 'land-sea mask'
        lm.standard_name = 'land_binary_mask'
        lm.units         = '1'
        lm.flag_values   = np.array([0, 1], dtype='f4')
        lm.flag_meanings = 'water land'

        hgt = ds.createVariable('HGT', 'f4', ('lat', 'lon'),
                                fill_value=MISSING_FLOAT, zlib=True)
        hgt.long_name     = 'model terrain height'
        hgt.standard_name = 'surface_altitude'
        hgt.units         = 'm'

        # ---- Helper to create 2D variable ----
        def _add_2d_var(name, std_name, long_name, units, extra):
            v = ds.createVariable(name, 'f4', ('time', 'lat', 'lon'),
                                  fill_value=MISSING_FLOAT, zlib=True)
            v.long_name     = long_name
            if std_name:
                v.standard_name = std_name
            v.units         = units
            v.coordinates   = 'lat lon'
            for k, val in extra.items():
                setattr(v, k, val)
            return v

        # ---- Helper to create 3D variable ----
        def _add_3d_var(name, std_name, long_name, units, extra):
            v = ds.createVariable(name, 'f4', ('time', 'pressure', 'lat', 'lon'),
                                  fill_value=MISSING_FLOAT, zlib=True)
            v.long_name     = long_name
            if std_name:
                v.standard_name = std_name
            v.units              = units
            v.coordinates        = 'lat lon pressure'
            v.interpolation_method = 'log-linear in pressure'
            for k, val in extra.items():
                setattr(v, k, val)
            return v

        # ---- Core 2D variables (mandatory) ----
        for vdef in CORE_2D_VARS:
            _add_2d_var(*vdef)

        # ---- Recommended 2D variables ----
        if include_recommended:
            for vdef in RECOMMENDED_2D_SURFACE_VARS:
                _add_2d_var(*vdef)
            for vdef in RECOMMENDED_2D_DIAG_VARS:
                _add_2d_var(*vdef)

        # ---- 3D variables on pressure levels ----
        if include_3d:
            for vdef in MANDATORY_3D_VARS:
                _add_3d_var(*vdef)
            if include_recommended:
                for vdef in RECOMMENDED_3D_VARS:
                    _add_3d_var(*vdef)

        # ---- Global attributes ----
        # CF convention
        ds.Conventions  = 'CF-1.8'
        ds.title        = (f"RUMI {info['experiment']} simulation: "
                           f"{info['event_name']}")
        ds.institution  = info['institution']
        ds.source       = f"{info['model']}"
        ds.history      = (f"Created {info['creation_date']} with "
                           f"{__title__} {__version__}")
        ds.references   = 'RUMI Protocol v1.2 (2026)'
        ds.comment      = 'Example output file — replace with actual model data'

        # RUMI-specific
        ds.experiment                   = info['experiment']
        ds.event                        = info['event']
        ds.event_name                   = info['event_name']
        ds.simulation_start_time        = info['simulation_start_time']
        ds.initialization_time          = info['initialization_time']
        ds.forecast_initialization_time = info['forecast_initialization_time']
        ds.forecast_lead_time_hours     = info['forecast_lead_time_hours']
        ds.forcing_data                 = info['forcing_data']
        ds.horizontal_resolution        = info['horizontal_resolution']
        ds.vertical_levels              = info['vertical_levels']
        ds.model_top_pressure           = info['model_top_pressure']

        # Contact
        ds.contact       = info['contact']
        ds.creator_name  = info['creator_name']
        ds.creation_date = info['creation_date']
        ds.version       = info['version']

        # Physics (update for your model)
        ds.microphysics_scheme     = info['microphysics_scheme']
        ds.cumulus_scheme          = info['cumulus_scheme']
        ds.pbl_scheme              = info['pbl_scheme']
        ds.radiation_scheme        = info['radiation_scheme']
        ds.land_surface_scheme     = info['land_surface_scheme']
        ds.urban_scheme            = info['urban_scheme']
        ds.surface_layer_scheme    = info['surface_layer_scheme']
        ds.turbulence_closure      = info['turbulence_closure']
        ds.landuse_dataset         = info['landuse_dataset']
        ds.urban_morphology_source = info['urban_morphology_source']
        ds.terrain_dataset         = info['terrain_dataset']
        ds.soil_dataset            = info['soil_dataset']

        # Output grid documentation
        ds.output_grid_type       = 'regular lat/lon'
        ds.output_grid_resolution = '15 arc-seconds (~0.004167 degrees)'
        ds.output_grid_lat_range  = f"{GRID['lat_south']}N to {GRID['lat_north']}N"
        ds.output_grid_lon_range  = f"{GRID['lon_west']}E to {GRID['lon_east']}E"
        ds.output_grid_dimensions = f"{GRID['nlon']} x {GRID['nlat']} (lon x lat)"

    print(f'Created empty RUMI NetCDF: {fpath}')
    return fpath


def fill_example_data(fpath):
    '''Fill the NetCDF file with synthetic example data for demonstration.

    Parameters
    ----------
    fpath : str
        Path to the NetCDF file created by create_rumi_netcdf()
    '''

    nlat = GRID['nlat']
    nlon = GRID['nlon']
    npres = len(PRESSURE_LEVELS)

    rng = np.random.default_rng(42)

    with nc.Dataset(fpath, mode='r+') as ds:

        # Surface fields
        ds.variables['LANDMASK'][:] = rng.choice([0, 1], size=(nlat, nlon), p=[0.4, 0.6]).astype('f4')
        ds.variables['HGT'][:] = rng.uniform(0, 500, size=(nlat, nlon)).astype('f4')

        # Core 2D — example values
        ds.variables['T2M'][0]         = rng.uniform(295, 310, (nlat, nlon)).astype('f4')
        ds.variables['U10M'][0]        = rng.uniform(-20, 20, (nlat, nlon)).astype('f4')
        ds.variables['V10M'][0]        = rng.uniform(-20, 20, (nlat, nlon)).astype('f4')
        ds.variables['PRATE'][0]       = rng.uniform(0, 0.01, (nlat, nlon)).astype('f4')
        ds.variables['SLP'][0]         = rng.uniform(100000, 102000, (nlat, nlon)).astype('f4')
        ds.variables['RH2M'][0]        = rng.uniform(0.5, 1.0, (nlat, nlon)).astype('f4')
        ds.variables['TOTAL_PRECIP'][0]= rng.uniform(0, 50, (nlat, nlon)).astype('f4')
        ds.variables['PSFC'][0]        = rng.uniform(99000, 102000, (nlat, nlon)).astype('f4')
        ds.variables['Q2M'][0]         = rng.uniform(0.010, 0.025, (nlat, nlon)).astype('f4')

        # Recommended 2D (if present)
        for vname in ['TSK', 'TD2M']:
            if vname in ds.variables:
                ds.variables[vname][0] = rng.uniform(295, 310, (nlat, nlon)).astype('f4')
        for vname in ['LH', 'HFX', 'SWDOWN', 'SWUP', 'LWDOWN', 'LWUP', 'GRDFLX']:
            if vname in ds.variables:
                ds.variables[vname][0] = rng.uniform(-50, 500, (nlat, nlon)).astype('f4')
        if 'WSPD10M' in ds.variables:
            ds.variables['WSPD10M'][0] = rng.uniform(0, 30, (nlat, nlon)).astype('f4')
        if 'WDIR10M' in ds.variables:
            ds.variables['WDIR10M'][0] = rng.uniform(0, 360, (nlat, nlon)).astype('f4')

        # 3D mandatory (if present)
        if 'T' in ds.variables and len(ds.variables['T'].dimensions) == 4:
            ds.variables['T'][0]     = rng.uniform(200, 310, (npres, nlat, nlon)).astype('f4')
            ds.variables['Z'][0]     = rng.uniform(0, 30000, (npres, nlat, nlon)).astype('f4')
            ds.variables['RH'][0]    = rng.uniform(0, 1, (npres, nlat, nlon)).astype('f4')
            ds.variables['U'][0]     = rng.uniform(-50, 50, (npres, nlat, nlon)).astype('f4')
            ds.variables['V'][0]     = rng.uniform(-50, 50, (npres, nlat, nlon)).astype('f4')
            ds.variables['OMEGA'][0] = rng.uniform(-5, 5, (npres, nlat, nlon)).astype('f4')

    print(f'Filled example data: {fpath}')


def main():
    '''Generate an example RUMI NetCDF file.'''
    print(f'{__title__} {__version__}')
    print(f'Output grid: {GRID["nlon"]} x {GRID["nlat"]} '
          f'({GRID["lon_west"]}-{GRID["lon_east"]}E, '
          f'{GRID["lat_south"]}-{GRID["lat_north"]}N), '
          f'15 arc-sec resolution')

    info = set_info()
    fpath = create_rumi_netcdf(info, include_recommended=True, include_3d=True)
    fill_example_data(fpath)

    # Verify
    with nc.Dataset(fpath, 'r') as ds:
        print(f'\nFile: {fpath}')
        print(f'Dimensions: {dict(ds.dimensions)}')
        print(f'Variables ({len(ds.variables)}): {list(ds.variables.keys())}')
        print(f'Global attrs: experiment={ds.experiment}, event={ds.event}')

    print('\nDone! Update set_info() and get_model_data() for your simulation.')


if __name__ == '__main__':
    main()
