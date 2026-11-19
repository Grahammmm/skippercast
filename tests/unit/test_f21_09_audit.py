"""The headline must include sampled requests beyond the top-40 route table."""
import io
import json
import unittest
from contextlib import redirect_stdout

from scripts import ops_report


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AllRoutesTests(unittest.TestCase):
    def test_weighted_headline_includes_the_41st_route(self):
        # Regression: summing the bounded table drops the least busy route's 5xx.
        points = [{'route': f'/r{i}', 'requests': 100, 's5xx': 0} for i in range(40)]
        points.append({'route': '/least', 'requests': 2, 's5xx': 2})
        queries = []

        def opener(request, timeout):
            sql = request.data.decode()
            queries.append(sql)
            if "index1 = 'request'" not in sql:
                rows = []
            elif 'GROUP BY' in sql.upper():
                rows = sorted(points, key=lambda row: -row['requests'])[:40]
            else:
                rows = [{'requests': sum(row['requests'] for row in points),
                         's5xx': sum(row['s5xx'] for row in points)}]
            return Response(json.dumps({'data': rows}).encode())

        with redirect_stdout(io.StringIO()) as output:
            status = ops_report.main([], {'CF_ANALYTICS_TOKEN': 'synthetic',
                                          'CLOUDFLARE_ACCOUNT_ID': 'synthetic'}, opener=opener)
        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn('Requests: 4,002; 5xx: 2 (0.05 %).', text)
        self.assertNotIn('| /least |', text)
        self.assertEqual(sum('| /r' in line for line in text.splitlines()), 40)
        request_queries = [sql for sql in queries if "index1 = 'request'" in sql]
        self.assertEqual(len(request_queries), 2)
        detail = next(sql for sql in request_queries if 'GROUP BY' in sql.upper())
        total = next(sql for sql in request_queries if 'GROUP BY' not in sql.upper())
        self.assertIn('LIMIT 40', detail.upper())
        self.assertNotIn('LIMIT', total.upper())
        for sql in request_queries:
            self.assertIn(ops_report.WINDOW, sql)
            self.assertIn('SUM(_sample_interval * double3) AS requests', sql)
            self.assertIn('sumIf(_sample_interval * double3, double1 >= 500) AS s5xx', sql)


if __name__ == '__main__':
    unittest.main()
