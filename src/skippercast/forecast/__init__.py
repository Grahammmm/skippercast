"""SkipperCast's own forecast grids built directly from NOAA and ECMWF open data.

Replaces the Open-Meteo API (free tier is non-commercial only). Python builds
compact regional tiles from the providers' GRIB files; one JavaScript sampler
(`server/model-api.js`) interpolates them to points and hours and answers in
Open-Meteo's response format, for the Worker and for this pipeline alike.
"""
