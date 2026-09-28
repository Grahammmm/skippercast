"""Model definitions: where each provider publishes, which fields, which hours.

Canonical stored units: m/s, m, s, degrees (direction the waves/wind come FROM),
degrees C, mm/h, %, m (visibility). Every field is regridded only by subsetting;
interpolation happens at sampling time.
"""
from dataclasses import dataclass, field

GFS_AWS = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
ECMWF_AWS = 'https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com'
ECMWF_PORTAL = 'https://data.ecmwf.int/forecasts'

# Box served to the app (it rejects points outside 32.4-42.1 N, 126-116.7 W),
# expanded to whole 1-degree tiles.
BOX = {'south': 32, 'north': 43, 'west': -127, 'east': -116}
HORIZON_HOURS = 192  # eight days


def hourly_then_3h(hourly_until, end=HORIZON_HOURS):
    return list(range(0, hourly_until + 1)) + list(range(hourly_until + 3, end + 1, 3))


ECMWF_STEPS = list(range(0, 145, 3)) + list(range(150, HORIZON_HOURS + 1, 6))


@dataclass(frozen=True)
class Field:
    name: str          # canonical field name in tiles
    select: tuple      # provider selector (GFS: (VAR, LEVEL[, extra]); ECMWF: (param,))
    scale: float       # int16 quantization step in canonical units
    convert: str = ''  # conversion applied after decoding


@dataclass(frozen=True)
class Model:
    id: str                 # Open-Meteo-compatible model id used by the app
    name: str
    provider: str
    kind: str               # 'wind' or 'wave'
    family: str             # 'gfs' or 'ecmwf'
    cycles: tuple           # initialization hours (UTC)
    steps: tuple
    fields: tuple
    resolution_km: int
    documentation: str
    mask: tuple = ()        # land-sea mask selector (atmospheric models)
    notes: str = ''
    cycle_delay_hours: float = 3.5  # typical time from initialization to full availability
    extra: dict = field(default_factory=dict)

    def field(self, name):
        return next(f for f in self.fields if f.name == name)


MODELS = {
    'gfs_global': Model(
        id='gfs_global', name='NOAA GFS', provider='NOAA NCEP', kind='wind', family='gfs',
        cycles=(0, 6, 12, 18), steps=tuple(hourly_then_3h(72)), resolution_km=13,
        documentation='https://registry.opendata.aws/noaa-gfs-bdp-pds/',
        # Wind, temperature and the land mask come from GFS's native ~13 km grid
        # ('native'); fields published only at 0.25° are regridded onto it.
        fields=(
            Field('u10', ('UGRD', '10 m above ground', 'native'), 0.01),
            Field('v10', ('VGRD', '10 m above ground', 'native'), 0.01),
            Field('gust', ('GUST', 'surface'), 0.01),
            Field('visibility', ('VIS', 'surface'), 10),
            Field('t2m', ('TMP', '2 m above ground', 'native'), 0.01, 'kelvin'),
            Field('precipitation', ('PRATE', 'surface'), 0.01, 'rate_per_hour'),
            Field('cloud_cover', ('TCDC', 'entire atmosphere'), 0.1),
        ),
        mask=('LAND', 'surface', 'native'),
        notes='Wind and temperature on the native ~13 km grid; gust, visibility, precipitation and cloud from the 0.25° product.',
        extra={'path': 'gfs.{date}/{hh}/atmos/gfs.t{hh}z.pgrb2.0p25.f{step:03d}',
               'native': 'gfs.{date}/{hh}/atmos/gfs.t{hh}z.sfluxgrbf{step:03d}.grib2'},
    ),
    'ecmwf_ifs025': Model(
        id='ecmwf_ifs025', name='ECMWF IFS', provider='ECMWF', kind='wind', family='ecmwf',
        cycles=(0, 12), steps=tuple(ECMWF_STEPS), resolution_km=25, cycle_delay_hours=7.5,
        documentation='https://www.ecmwf.int/en/forecasts/datasets/open-data',
        fields=(
            Field('u10', ('10u',), 0.01),
            Field('v10', ('10v',), 0.01),
            # Usually '10fg'; some steps publish the same maximum as '10fg3' or '10fg6'.
            Field('gust', ('10fg', '10fg3', '10fg6'), 0.01),
            Field('t2m', ('2t',), 0.01, 'kelvin'),
            Field('precipitation', ('tp',), 0.01, 'accumulated_m'),
            Field('cloud_cover', ('tcc',), 0.1, 'fraction'),
        ),
        mask=('lsm',),
        notes='ECMWF open data has no visibility; 10 m gust is the maximum over the preceding hour.',
        extra={'stream': 'oper'},
    ),
    'ncep_gfswave016': Model(
        id='ncep_gfswave016', name='NOAA GFS Wave 0.16°', provider='NOAA NCEP', kind='wave', family='gfs',
        cycles=(0, 6, 12, 18), steps=tuple(hourly_then_3h(72)), resolution_km=18,
        documentation='https://registry.opendata.aws/noaa-gfs-bdp-pds/',
        fields=(
            Field('wave_height', ('HTSGW', 'surface'), 0.01),
            Field('wave_period', ('PERPW', 'surface'), 0.01),
            Field('wave_direction', ('DIRPW', 'surface'), 0.1),
            Field('wind_wave_height', ('WVHGT', 'surface'), 0.01),
            Field('wind_wave_period', ('WVPER', 'surface'), 0.01),
            Field('wind_wave_direction', ('WVDIR', 'surface'), 0.1),
            Field('swell_wave_height', ('SWELL', '1 in sequence'), 0.01),
            Field('swell_wave_period', ('SWPER', '1 in sequence'), 0.01),
            Field('swell_wave_direction', ('SWDIR', '1 in sequence'), 0.1),
            Field('secondary_swell_wave_height', ('SWELL', '2 in sequence'), 0.01),
            Field('secondary_swell_wave_period', ('SWPER', '2 in sequence'), 0.01),
            Field('secondary_swell_wave_direction', ('SWDIR', '2 in sequence'), 0.1),
        ),
        notes='US West Coast 0.16° grid. Wave period is the peak period.',
        extra={'path': 'gfs.{date}/{hh}/wave/gridded/gfswave.t{hh}z.wcoast.0p16.f{step:03d}.grib2'},
    ),
    'ecmwf_wam': Model(
        id='ecmwf_wam', name='ECMWF WAM', provider='ECMWF', kind='wave', family='ecmwf',
        cycles=(0, 12), steps=tuple(ECMWF_STEPS), resolution_km=25, cycle_delay_hours=7.5,
        documentation='https://www.ecmwf.int/en/forecasts/datasets/open-data',
        fields=(
            Field('wave_height', ('swh',), 0.01),
            Field('wave_period', ('mwp',), 0.01),
            Field('wave_peak_period', ('pp1d',), 0.01),
            Field('wave_direction', ('mwd',), 0.1),
        ),
        notes='ECMWF open data publishes total sea state only; wind-wave and swell components are unavailable.',
        extra={'stream': 'wave'},
    ),
}
