"""Interpret producer-documented resolution zones in original depth grids.

The delivered GeoTIFF may have a finer display spacing than the acquisition
grid used in deep water. Deep pixels remain mapped tier 1, but cannot support
fine-detail terrain or pile-scale habitat until a coarse-grid path exists.
"""


def fine_detail_valid(depth, valid, row):
    profile = row.get('resolution_profile')
    if profile is None:
        return valid
    return valid & (depth < profile['fine_to_depth_m'])
