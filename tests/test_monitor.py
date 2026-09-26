"""Offline fixtures exercise incomplete evidence and alert lifecycle boundaries."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from skippercast.monitor import collector
from skippercast.monitor.lifecycle import action_for, fingerprint, qualifies


TZ = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 9, 20)


def fixture_config():
    return {"source_profile": "morro-bay", "timezone": str(TZ), "weather_sampling_points": [
        {"name": "test_entrance", "latitude": 35.358, "longitude": -120.877},
    ]}


def fixture_dataset(source):
    start = datetime.combine(TODAY, datetime.min.time())
    times = [(start + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(8 * 24)]
    variables = collector.WIND_VARIABLES if source == "wind-models" else collector.WAVE_VARIABLES
    models = collector.WIND_MODELS if source == "wind-models" else collector.WAVE_MODELS
    hourly, units = {"time": times}, {"time": "iso8601"}
    for model in models:
        for variable in variables:
            key = f"{variable}_{model}"
            if variable in ("wind_speed_10m", "wind_gusts_10m"):
                unit, value = "kn", 6 if variable == "wind_speed_10m" else 8
            elif variable.endswith("height"):
                unit, value = "m", 0.5
            elif variable.endswith("period"):
                unit, value = "s", 12
            elif "direction" in variable:
                unit, value = "°", 270
            elif variable == "visibility":
                unit, value = "m", 10000
            elif variable == "precipitation":
                unit, value = "mm", 0
            else:
                unit, value = "wmo code", 0
            hourly[key], units[key] = [value] * len(times), unit
    return {"latitude": 35.25, "longitude": -121, "timezone": str(TZ),
            "hourly": hourly, "hourly_units": units}


def write_fixture(path, *, wind=None, wave=None, metadata_end=None):
    initialization = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    metadata = {"last_run_initialisation_time": initialization.timestamp(),
                "last_run_availability_time": (initialization + timedelta(hours=7)).timestamp(),
                "data_end_time": (metadata_end or initialization + timedelta(days=10)).timestamp()}
    for name in collector.META_NAMES:
        (path / f"{name}.raw.txt").write_text(json.dumps(metadata), encoding="utf-8")
    for name, dataset in (("wind-models", wind), ("wave-models", wave)):
        (path / f"{name}.raw.txt").write_text(json.dumps([
            dataset if dataset is not None else fixture_dataset(name)
        ]), encoding="utf-8")


class CollectorFixtures(unittest.TestCase):
    def screen(self, **kwargs):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            write_fixture(out, **kwargs)
            result = collector.summarize(out, fixture_config(), TODAY)
            self.assertEqual(json.loads((out / "screen.json").read_text()), result)
            return result

    def test_complete_fixture_preserves_local_future_dates_and_units(self):
        result = self.screen()
        self.assertEqual(result["data_gaps"], [])
        self.assertEqual(result["timezone"], "America/Los_Angeles")
        self.assertEqual(result["forecast_dates"], [f"2026-09-{day}" for day in range(21, 28)])
        wave_row = result["locations"][1]["daily_06_to_13_screen"][0]
        self.assertEqual(wave_row["hour_count"], 8)
        self.assertEqual(wave_row["ranges"]["wave_height_ecmwf_wam"], {
            "min": 1.64, "max": 1.64, "available_hours": 8, "unit": "ft",
        })

    def test_absent_variable_is_explicitly_unknown(self):
        wind = fixture_dataset("wind-models")
        del wind["hourly"]["wind_gusts_10m_gfs_global"]
        result = self.screen(wind=wind)
        self.assertTrue(any("wind_gusts_10m_gfs_global absent" in gap for gap in result["data_gaps"]))
        entry = result["locations"][0]
        self.assertIn("wind_gusts_10m_gfs_global", entry["unavailable_variables"])
        self.assertEqual(entry["daily_06_to_13_screen"][0]["ranges"]["wind_gusts_10m_gfs_global"]["min"], None)
        self.assertEqual(entry["gust_below_sustained_flags"], [])

    def test_truncated_and_malformed_arrays_do_not_crash_or_fill_values(self):
        wind = fixture_dataset("wind-models")
        wind["hourly"]["wind_speed_10m_gfs_global"] = [6] * 32
        wind["hourly"]["visibility_ecmwf_ifs025"] = {"bad": "shape"}
        result = self.screen(wind=wind)
        self.assertTrue(any("length 32 differs" in gap for gap in result["data_gaps"]))
        row = result["locations"][0]["daily_06_to_13_screen"][0]
        self.assertEqual(row["ranges"]["wind_speed_10m_gfs_global"]["available_hours"], 2)
        self.assertEqual(row["ranges"]["visibility_ecmwf_ifs025"]["available_hours"], 0)

    def test_invalid_numbers_are_gaps_and_never_json_nan(self):
        wind = fixture_dataset("wind-models")
        wind["latitude"] = float("nan")
        values = wind["hourly"]["wind_speed_10m_ecmwf_ifs025"]
        values[30:34] = [float("nan"), float("inf"), "6", True]
        result = self.screen(wind=wind)
        self.assertTrue(any("invalid numeric" in gap for gap in result["data_gaps"]))
        self.assertIsNone(result["locations"][0]["returned_grid"]["latitude"])
        row = result["locations"][0]["daily_06_to_13_screen"][0]
        self.assertEqual(row["ranges"]["wind_speed_10m_ecmwf_ifs025"]["available_hours"], 4)

    def test_all_null_variables_are_unavailable_and_gaps(self):
        wave = fixture_dataset("wave-models")
        wave["hourly"]["secondary_swell_wave_height_ecmwf_wam"] = [None] * 192
        result = self.screen(wave=wave)
        self.assertTrue(any("secondary_swell_wave_height_ecmwf_wam incomplete" in gap for gap in result["data_gaps"]))

    def test_gust_below_wind_is_flagged_without_correction(self):
        wind = fixture_dataset("wind-models")
        wind["hourly"]["wind_gusts_10m_gfs_global"][30] = 4
        result = self.screen(wind=wind)
        flags = result["locations"][0]["gust_below_sustained_flags"]
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["gust"], 4)
        self.assertEqual(flags[0]["sustained"], 6)
        self.assertTrue(any("gust-below-sustained" in gap for gap in result["data_gaps"]))

    def test_duplicate_or_invalid_times_cannot_create_complete_hours(self):
        wind = fixture_dataset("wind-models")
        wind["hourly"]["time"][30] = "invalid"
        wind["hourly"]["time"][31] = wind["hourly"]["time"][32]
        result = self.screen(wind=wind)
        self.assertEqual(result["locations"][0]["daily_06_to_13_screen"][0]["hour_count"], 5)
        self.assertTrue(any("duplicate hourly" in gap for gap in result["data_gaps"]))

    def test_invalid_time_array_and_missing_location_return_gaps(self):
        wind = fixture_dataset("wind-models")
        wind["hourly"]["time"] = None
        result = self.screen(wind=wind)
        self.assertTrue(any("hourly.time" in gap for gap in result["data_gaps"]))
        with TemporaryDirectory() as directory:
            out = Path(directory)
            write_fixture(out)
            (out / "wind-models.raw.txt").write_text("[]", encoding="utf-8")
            result = collector.summarize(out, fixture_config(), TODAY)
            self.assertTrue(any("returned 0 locations" in gap for gap in result["data_gaps"]))
            self.assertEqual(result["locations"][0]["daily_06_to_13_screen"][0]["hour_count"], 0)

    def test_model_latest_coverage_does_not_attribute_later_forecast_values(self):
        result = self.screen(metadata_end=datetime(2026, 9, 26, 21, tzinfo=timezone.utc))
        self.assertEqual(len([gap for gap in result["data_gaps"] if "published coverage" in gap]), 4)
        self.assertEqual(result["locations"][0]["daily_06_to_13_screen"][-1]["hour_count"], 8)

    def test_date_selection_uses_pacific_even_when_utc_date_is_tomorrow(self):
        utc = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)
        urls = collector.sources(fixture_config(), utc)
        query = parse_qs(urlparse(urls["port-san-luis-tides-reference-only"]).query)
        self.assertEqual(query["begin_date"], ["20260920"])
        with TemporaryDirectory() as directory:
            out = Path(directory)
            write_fixture(out)
            self.assertEqual(collector.summarize(out, fixture_config(), utc)["local_date"], "2026-09-20")

    def test_wrong_units_are_not_labelled_as_knots(self):
        wind = fixture_dataset("wind-models")
        wind["hourly_units"]["wind_speed_10m_gfs_global"] = "m/s"
        result = self.screen(wind=wind)
        self.assertTrue(any("unexpected wind unit" in gap for gap in result["data_gaps"]))
        row = result["locations"][0]["daily_06_to_13_screen"][0]
        self.assertEqual(row["ranges"]["wind_speed_10m_gfs_global"]["unit"], "m/s")


class CollectorConfiguration(unittest.TestCase):
    def test_example_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "configs" / "morro-bay.example.json"
        self.assertEqual(collector.validate_config(json.loads(path.read_text()))["source_profile"], "morro-bay")

    def test_private_fields_wrong_region_and_duplicate_names_are_rejected(self):
        config = fixture_config()
        config["telegram_token"] = "fixture-not-a-real-token"
        with self.assertRaises(ValueError):
            collector.validate_config(config)
        config = fixture_config()
        config["weather_sampling_points"][0]["latitude"] = 45
        with self.assertRaises(ValueError):
            collector.validate_config(config)
        config = fixture_config()
        config["weather_sampling_points"] *= 2
        with self.assertRaises(ValueError):
            collector.validate_config(config)

    def test_bad_timezone_and_nan_are_rejected(self):
        config = fixture_config()
        config["timezone"] = "UTC"
        with self.assertRaises(ValueError):
            collector.validate_config(config)
        config = fixture_config()
        config["weather_sampling_points"][0]["longitude"] = float("nan")
        with self.assertRaises(ValueError):
            collector.validate_config(config)

    def test_cli_incomplete_is_nonzero_and_saves_failure_evidence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "profile.json"
            config.write_text(json.dumps(fixture_config()), encoding="utf-8")
            out = root / "run"
            def fake_fetch(name, url, output):
                record = {"name": name, "url": url, "error": "offline fixture failure"}
                (output / f"{name}.meta.json").write_text(json.dumps(record), encoding="utf-8")
                return record
            with patch.object(collector, "fetch", fake_fetch), redirect_stdout(io.StringIO()):
                status = collector.main(["--config", str(config), "--output", str(out)])
            self.assertEqual(status, 1)
            result = json.loads((out / "result.json").read_text())
            self.assertEqual(result["status"], "incomplete")
            self.assertTrue(result["source_failures"])
            self.assertTrue((out / "manifest.json").exists())
            self.assertTrue((out / "screen.json").exists())
            with patch.object(collector, "fetch") as fetch, redirect_stderr(io.StringIO()):
                self.assertEqual(collector.main(["--config", str(config), "--output", str(out)]), 2)
                fetch.assert_not_called()


class AlertLifecycle(unittest.TestCase):
    def setUp(self):
        self.good = {"comfort_score": 9, "fishing_conditions_score": 9,
                     "confidence": "Moderate", "verification_complete": True,
                     "meets_numeric_targets": True, "hazards": [], "critical_gaps": [],
                     "area": "Morro Bay", "departure": "07:00", "return": "12:30"}
        self.previous = {"ever_alerted": True, "qualified_at_last_alert": True,
                         "material_fingerprint": fingerprint(self.good)}

    def test_initial_and_unchanged(self):
        now = datetime(2026, 9, 21, 6, tzinfo=TZ)
        self.assertEqual(action_for("2026-09-24", self.good, {}, now), "Early opportunity")
        self.assertIsNone(action_for("2026-09-24", self.good, self.previous, now))

    def test_missing_data_retracts(self):
        changed = dict(self.good, critical_gaps=["return forecast unavailable"])
        self.assertFalse(qualifies(changed))
        self.assertEqual(action_for("2026-09-24", changed, self.previous,
                                    datetime(2026, 9, 22, 6, tzinfo=TZ)), "No longer qualifies")

    def test_absent_null_and_invalid_fields_never_qualify(self):
        for key in self.good:
            if key in ("area", "departure", "return"):
                continue
            with self.subTest(missing=key):
                changed = dict(self.good)
                del changed[key]
                self.assertFalse(qualifies(changed))
            with self.subTest(null=key):
                self.assertFalse(qualifies(dict(self.good, **{key: None})))
        for change in [{"comfort_score": True}, {"comfort_score": float("nan")},
                       {"comfort_score": float("inf")}, {"fishing_conditions_score": 8},
                       {"confidence": "Low"}, {"hazards": ["Small Craft Advisory"]},
                       {"verification_complete": "true"}, {"comfort_score": 11}]:
            with self.subTest(change=change):
                self.assertFalse(qualifies(dict(self.good, **change)))

    def test_return_change_gets_update(self):
        changed = dict(self.good, **{"return": "12:00"})
        self.assertEqual(action_for("2026-09-24", changed, self.previous,
                                    datetime(2026, 9, 22, 6, tzinfo=TZ)), "Update")

    def test_final_even_if_unchanged_or_retracted(self):
        now = datetime(2026, 9, 23, 18, tzinfo=TZ)
        self.assertEqual(action_for("2026-09-24", self.good, self.previous, now), "Day-before assessment")
        previous = dict(self.previous, qualified_at_last_alert=False)
        self.assertEqual(action_for("2026-09-24", {}, previous, now), "Day-before assessment")
        previous["final_assessment_delivered"] = True
        self.assertIsNone(action_for("2026-09-24", self.good, previous, now))

    def test_missed_final_is_reported_once_and_never_backdated(self):
        now = datetime(2026, 9, 24, 6, tzinfo=TZ)
        self.assertEqual(action_for("2026-09-24", {}, self.previous, now), "Missed final assessment")
        previous = dict(self.previous, missed_final_reported=True)
        self.assertIsNone(action_for("2026-09-24", {}, previous, now))

    def test_first_qualification_on_previous_evening_is_final(self):
        self.assertEqual(action_for("2026-09-24", self.good, {},
                                    datetime(2026, 9, 23, 18, tzinfo=TZ)), "Day-before assessment")

    def test_naive_time_is_rejected_and_input_state_is_not_modified(self):
        with self.assertRaises(ValueError):
            action_for("2026-09-24", self.good, self.previous, datetime(2026, 9, 23, 18))
        before = dict(self.previous)
        action_for("2026-09-24", self.good, self.previous, datetime(2026, 9, 23, 18, tzinfo=TZ))
        self.assertEqual(self.previous, before)


if __name__ == "__main__":
    unittest.main()
