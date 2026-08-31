"""Admin-curated participation profiles derived from the RUMI summary.

The registry links an approved POC account to the participation information
that is already known to the coordination team. It is deliberately limited to
planning metadata; NetCDF and archive contents remain a separate validation
concern.
"""


PARTICIPATION_PROFILE_SEEDS = (
    {
        "profile_key": "hkust-mpas",
        "poc_email": "shixm@ust.hk",
        "group_name": "HKUST MPAS",
        "model": "MPAS",
        "forcing_sources": "ERA5, GFS",
        "case_studies": "Tropical cyclone, heavy rain, heat",
        "timeline": "Autumn",
        "poc_surname": "SHI",
        "participants": "Xiaoming Shi, Fei Chen, Zhuo Liu, etc.",
        "notes": "POC: Xiaoming Shi",
        "source": "RUMI Participation Summary.docx",
    },
    {
        "profile_key": "hkust-wrf-uacm",
        "poc_email": "jhucj@connect.ust.hk",
        "group_name": "HKUST WRF-UACM",
        "model": "WRF-UACM",
        "forcing_sources": "ERA5, GFS",
        "case_studies": "Tropical cyclone, heavy rain, heat",
        "timeline": "Autumn",
        "poc_surname": "HU",
        "participants": "Junhao Hu, Utkarsh Bhautmage, Jimmy Fung",
        "notes": "POC: Junhao Hu",
        "source": "RUMI Participation Summary.docx",
    },
)
