Attributes {
    waveTime {
        String long_name "UTC prediction time";
        String standard_name "time";
        String units "seconds since 1970-01-01 00:00:00 UTC";
        String calendar "standard";
        String axis "T";
        String coverage_content_type "coordinate";
    }
    waveFlagPrimary {
        String _Unsigned "false";
        String long_name "primary wave QC flag";
        Int16 _FillValue -127;
        Byte valid_min 1;
        Byte valid_max 9;
        Byte flag_values 1, 2, 3, 4, 9;
        String flag_meanings "good not_evaluated questionable bad missing";
        String reference "Ocean Data Standards, UNESCO 2013 - IOC Manuals and Guides, 54, Volume 3 Version 1";
        String ancillary_variables "waveFlagSecondary";
    }
    waveFlagSecondary {
        String _Unsigned "false";
        String long_name "secondary model QC flag";
        Int16 _FillValue -127;
        Byte valid_min 0;
        Byte valid_max 2;
        Byte flag_values 0, 1, 2;
        String flag_meanings "unspecified insufficient_input low_energy";
        String reference "http://cdip.ucsd.edu/documentation";
    }
    waveHs {
        String long_name "significant wave height";
        String units "meter";
        Float32 _FillValue -999.99;
        String standard_name "sea_surface_wave_significant_height";
        String coordinates "metaLatitude metaLongitude";
        String grid_mapping "metaGridMapping";
        Float32 valid_min 0.0;
        Float32 valid_max 20.0;
        String ancillary_variables "waveFlagPrimary waveFlagSecondary";
        String ncei_name "WAVE HEIGHT - SIGNIFICANT";
    }
    waveTp {
        String long_name "peak wave period";
        String units "second";
        Float32 _FillValue -999.99;
        String standard_name "sea_surface_wave_period_at_variance_spectral_density_maximum";
        String coordinates "metaLatitude metaLongitude";
        String grid_mapping "metaGridMapping";
        Float32 valid_min 0.0;
        Float32 valid_max 40.0;
        String ancillary_variables "waveFlagPrimary waveFlagSecondary";
        String ncei_name "WAVE - PEAK PERIOD";
    }
    waveDp {
        String long_name "peak wave direction";
        String units "degreeT";
        Float32 _FillValue -999.99;
        String standard_name "sea_surface_wave_from_direction";
        String coordinates "metaLatitude metaLongitude";
        String grid_mapping "metaGridMapping";
        Float32 valid_min 0.0;
        Float32 valid_max 360.0;
        String ancillary_variables "waveFlagPrimary waveFlagSecondary";
        String ncei_name "WAVE DIRECTION";
    }
    NC_GLOBAL {
        String date_created "2026-10-08T13:47:44Z";
        String date_modified "2026-10-08T13:47:44Z";
        String id "MOPv1.1_SL345_2026100500-2026101423";
        String time_coverage_resolution "PT03H00M";
        String date_issued "2026-10-08T13:47:44Z";
        String institution "Scripps Institution of Oceanography, University of California San Diego";
        String license "These data may be redistributed and used without restriction.";
    }
}
