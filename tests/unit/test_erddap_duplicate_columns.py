import copy
import unittest

from skippercast.pipeline import parsers

T = "2026-09-20T12:00:00Z"
META = {"attrs": {"NC_GLOBAL": {"title": "t"}, "chlorophyll": {"_FillValue": "-999"}}}
BASE = ["time", "latitude", "longitude", "chlorophyll"]
BASE_U = ["UTC", "degrees_north", "degrees_east", "mg m-3"]
DUP = "Duplicate ERDDAP column names"


def grid(names, units, rows):
    return {"table": {"columnNames": names, "columnUnits": units, "rows": rows}}


class ErddapDuplicateColumnTests(unittest.TestCase):
    def refuse(self, data, variables, kind):
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError) as ctx:
            parsers.erddap_grid(data, META, variables, kind)
        self.assertEqual(str(ctx.exception), DUP)
        self.assertEqual(data, before)

    def test_duplicate_measurement_refuses_instead_of_overwriting(self):
        names, units = BASE + ["chlorophyll"], BASE_U + ["mg m-3"]
        for a, b in ((1, 25), (25, 1), (1, 1)):
            self.refuse(grid(names, units, [[T, 35.0, -121.0, a, b]]), ["chlorophyll"], "chlorophyll")
        self.refuse(grid(names, BASE_U + ["other"], [[T, 35.0, -121.0, 1, 1]]), ["chlorophyll"], "chlorophyll")

    def test_duplicate_coordinates_time_and_quality_refuse(self):
        for extra, unit in (("latitude", "degrees_north"), ("longitude", "degrees_east"), ("time", "UTC")):
            self.refuse(grid(BASE + [extra], BASE_U + [unit], [[T, 35.0, -121.0, 1.0, 35.0]]),
                        ["chlorophyll"], "chlorophyll")
        sst = ["time", "latitude", "longitude", "analysed_sst", "mask", "mask"]
        self.refuse(grid(sst, ["UTC", "d", "d", "degree_C", "1", "1"], [[T, 35.0, -121.0, 15.0, 1, 1]]),
                    ["analysed_sst"], "sst")
        cur = ["time", "latitude", "longitude", "water_u", "water_v", "number_of_sites", "number_of_sites"]
        self.refuse(grid(cur, ["UTC", "d", "d", "m s-1", "m s-1", "1", "1"], [[T, 35.0, -121.0, 1, 1, 3, 3]]),
                    ["water_u", "water_v"], "currents")

    def test_duplicate_header_refuses_before_empty_rows(self):
        self.refuse(grid(BASE + ["extra", "extra"], BASE_U + ["x", "x"], []), ["chlorophyll"], "chlorophyll")
        with self.assertRaises(ValueError) as ctx:
            parsers.erddap_grid(grid(BASE, BASE_U, []), META, ["chlorophyll"], "chlorophyll")
        self.assertEqual(str(ctx.exception), "Empty ERDDAP grid")

    def test_unique_headers_preserve_complete_grid(self):
        rows = [[T, 35.3, -121.5, -999], [T, 35.4, -121.5, 2.3]]
        r = parsers.erddap_grid(grid(BASE, BASE_U, rows), META, ["chlorophyll"], "chlorophyll")
        self.assertEqual(r["valid_cells"], 1)
        self.assertEqual(r["total_cells"], 2)
        self.assertEqual(r["units"], dict(zip(BASE, BASE_U)))
        self.assertEqual(r["samples"], [
            {"time": T, "latitude": 35.3, "longitude": -121.5, "chlorophyll": None},
            {"time": T, "latitude": 35.4, "longitude": -121.5, "chlorophyll": 2.3}])
        order = [3, 1, 0, 2]
        names = [BASE[i] for i in order] + ["Extra"]
        r2 = parsers.erddap_grid(
            grid(names, [BASE_U[i] for i in order] + ["x"], [[row[i] for i in order] + [9] for row in rows]),
            META, ["chlorophyll"], "chlorophyll")
        self.assertEqual([{k: v for k, v in s.items() if k != "Extra"} for s in r2["samples"]],
                         [{k: s[k] for k in BASE} for s in r["samples"]])
        self.assertEqual(r2["valid_cells"], 1)


if __name__ == "__main__":
    unittest.main()
