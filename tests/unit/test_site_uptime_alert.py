from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

from scripts import site_uptime_alert as uptime

T0 = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
OK = {"/api/health": (200, '{"ok": true}'), "/": (200, "<html>"), "/map": (200, "<html>")}


class FakeSite:
    """A real HTTP server on 127.0.0.1. routes: path -> list of (status, body[, location|delay]); each hit consumes one, the last repeats."""

    def __init__(self, routes):
        self.routes, self.hits = {p: r if isinstance(r, list) else [r] for p, r in routes.items()}, []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                site.hits.append(self.path)
                queue = site.routes[self.path]
                status, body, *extra = queue.pop(0) if len(queue) > 1 else queue[0]
                if extra and isinstance(extra[0], float):
                    time.sleep(extra[0])
                self.send_response(status)
                if extra and isinstance(extra[0], str):
                    self.send_header("Location", extra[0])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body.encode())
                except OSError:
                    pass  # the client gave up (timeout case)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"


class FakeGitHub:
    """Just enough of `gh issue ...`: open `site-down` issues, their age and comments."""

    def __init__(self, clock):
        self.clock, self.issues, self.calls = clock, [], []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps([i for i in self.issues if i["state"] == "open"])
        if args[:2] == ("issue", "create"):
            self.issues.append({"number": len(self.issues) + 1, "title": args[args.index("--title") + 1], "state": "open",
                                "body": args[args.index("--body") + 1], "label": args[args.index("--label") + 1],
                                "createdAt": self.clock().isoformat(), "comments": []})
        elif args[:2] == ("issue", "comment"):
            self.issues[int(args[2]) - 1]["comments"].append({"body": args[args.index("--body") + 1]})
        elif args[:2] == ("issue", "close"):
            issue = self.issues[int(args[2]) - 1]
            issue["state"] = "closed"
            issue["comments"].append({"body": args[args.index("--comment") + 1]})
        return ""

    def writes(self):
        return [c for c in self.calls if c[:2] != ("issue", "list")]


class SiteUptimeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.report, self.now, self.sites = Path(tmp.name) / "site-uptime.json", T0, []
        self.gh = FakeGitHub(lambda: self.now)

    def site(self, **overrides):
        self.sites.append(FakeSite({**OK, **{k.replace("_", "/") if k != "root" else "/": v for k, v in overrides.items()}}))
        return self.sites[-1]

    def run_once(self, site, *extra, timeout=2.0):
        code = uptime.main(["--base", site.base, "--report", str(self.report), *extra], runner=self.gh, now=self.now,
                           retry_delay=0, sleep=lambda s: None, timeout=timeout)
        self.assertEqual(code, 0)
        return json.loads(self.report.read_text())

    def test_all_up_reports_up_and_makes_no_write_call(self):
        report = self.run_once(self.site())
        self.assertEqual((report["down"], report["failures"]), (False, []))
        self.assertTrue(report["checked_at"])
        self.assertEqual(self.gh.writes(), [])

    def test_health_503_twice_opens_one_issue_and_a_second_run_stays_quiet(self):
        site = self.site(_api_health=(503, "boom secret-body"))
        self.assertTrue(self.run_once(site)["down"])
        self.assertEqual(site.hits.count("/api/health"), 2)  # first try + one retry
        self.assertEqual(site.hits.count("/map"), 1)  # a path that answered is not retried
        issue = self.gh.issues[0]
        self.assertEqual((issue["title"], issue["label"]), (uptime.TITLE, "site-down"))
        self.assertIn("- /api/health 503", issue["body"])
        self.assertNotIn("secret-body", issue["body"])
        self.assertNotIn("/map", issue["body"])
        self.now = T0 + timedelta(hours=1)
        self.run_once(site)
        self.assertEqual((len(self.gh.writes()), issue["comments"]), (1, []))

    def test_first_try_timeout_then_200_is_up(self):
        site = self.site(root=[(200, "slow", 1.0), (200, "<html>")])
        self.assertFalse(self.run_once(site, timeout=0.2)["down"])
        self.assertEqual(site.hits.count("/"), 2)
        self.assertEqual(self.gh.writes(), [])

    def test_timeout_on_both_tries_is_down_as_timeout(self):
        report = self.run_once(self.site(_map=(200, "slow", 1.0)), timeout=0.2)
        self.assertEqual(report["failures"], [{"path": "/map", "error": "timeout"}])
        self.assertIn("- /map timeout", self.gh.issues[0]["body"])

    def test_health_that_is_not_a_json_object_is_down_as_not_json(self):
        for body in ("<html>ok</html>", "[1, 2]", ""):
            with self.subTest(body=body):
                report = self.run_once(self.site(_api_health=(200, body)), "--dry-run")
                self.assertEqual(report["failures"], [{"path": "/api/health", "status": 200, "error": "not JSON"}])
        self.assertFalse(self.run_once(self.site(), "--dry-run")["down"])  # HTML is the right answer for / and /map

    def test_still_down_comments_once_per_interval_then_recovery_closes_with_duration(self):
        down = self.site(_api_health=(503, ""))
        self.run_once(down)
        issue = self.gh.issues[0]
        self.now = T0 + timedelta(hours=5)
        self.run_once(down)
        self.assertEqual(issue["comments"], [])  # inside the first STILL_HOURS interval
        self.now = T0 + timedelta(hours=6, minutes=2)
        self.run_once(down)
        self.run_once(down)  # same interval again: idempotent
        self.assertEqual([c["body"].split(" - ")[0] for c in issue["comments"]], ["still: 6 h"])
        self.assertIn("/api/health 503", issue["comments"][0]["body"])
        self.now = T0 + timedelta(hours=7, minutes=30)
        self.run_once(self.site())
        self.assertEqual(issue["state"], "closed")
        self.assertIn("was down for 7 h 30 min", issue["comments"][-1]["body"])
        self.assertEqual(len(self.gh.writes()), 3)  # create, one still, close
        self.run_once(self.site())  # up again with nothing open: no reopen, no comment
        self.assertEqual(len(self.gh.writes()), 3)

    def test_dry_run_makes_no_gh_call_but_writes_the_report(self):
        self.assertTrue(self.run_once(self.site(_api_health=(503, "")), "--dry-run")["down"])
        self.assertEqual(self.gh.calls, [])

    def test_unresolvable_host_reports_a_dns_error_in_dry_run(self):
        code = uptime.main(["--base", "https://example.invalid", "--report", str(self.report), "--dry-run"],
                           runner=self.gh, retry_delay=0, sleep=lambda s: None)
        report = json.loads(self.report.read_text())
        self.assertEqual((code, report["down"]), (0, True))
        self.assertEqual({f["error"] for f in report["failures"]}, {"dns error"})
        self.assertEqual(self.gh.calls, [])

    def test_redirect_to_another_host_is_down_and_never_followed(self):
        site = self.site(root=(301, "", "http://other.invalid/landing?token=hunter2"))
        report = self.run_once(site)
        self.assertEqual(report["failures"], [{"path": "/", "status": 301, "error": "redirect"}])
        text = json.dumps(self.gh.issues) + json.dumps(report)
        for leak in ("other.invalid", "hunter2", "token", "?"):
            self.assertNotIn(leak, text)
        self.assertIn("- / redirect 301", self.gh.issues[0]["body"])

    def test_dropped_or_malformed_response_is_down_not_a_crash(self):
        for reply, name in ((b"", "RemoteDisconnected"), (b"garbage\r\n\r\n", "BadStatusLine")):
            with self.subTest(name=name):
                listener = socket.create_server(("127.0.0.1", 0))
                self.addCleanup(listener.close)

                def serve(sock=listener, reply=reply):
                    while True:
                        try:
                            conn, _ = sock.accept()
                        except OSError:
                            return
                        with conn:
                            conn.recv(4096)
                            conn.sendall(reply)

                threading.Thread(target=serve, daemon=True).start()
                base = f"http://127.0.0.1:{listener.getsockname()[1]}"
                code = uptime.main(["--base", base, "--report", str(self.report), "--dry-run"], runner=self.gh,
                                   retry_delay=0, sleep=lambda s: None, timeout=2.0)
                report = json.loads(self.report.read_text())
                self.assertEqual((code, report["down"]), (0, True))
                self.assertEqual({f["error"] for f in report["failures"]}, {name})

    def test_internal_probe_error_propagates_without_report_or_issue(self):
        site = self.site()
        with mock.patch.object(uptime.request, "build_opener", side_effect=RuntimeError("bug")):
            with self.assertRaises(RuntimeError):
                uptime.main(["--base", site.base, "--report", str(self.report)], runner=self.gh,
                            retry_delay=0, sleep=lambda s: None, timeout=2.0)
        self.assertFalse(self.report.exists())
        self.assertEqual((self.gh.calls, self.gh.issues), ([], []))

    def test_redirect_within_the_same_host_is_followed(self):
        self.assertFalse(self.run_once(self.site(root=(302, "", "/map")), "--dry-run")["down"])

    def test_missing_or_invalid_base_exits_2_without_probe_or_issue(self):
        for argv in ([], ["--base", ""], ["--base", "ftp://site.example"], ["--base", "site.example"], ["--base", "https://"],
                     ["--base", "file:///etc/passwd"]):
            with self.subTest(argv=argv):
                code = uptime.main([*argv, "--report", str(self.report)], runner=self.gh, retry_delay=0, sleep=lambda s: None)
                self.assertEqual(code, 2)
                self.assertFalse(self.report.exists())
                self.assertEqual(self.gh.calls, [])

    def test_plan_stays_quiet_before_the_interval_and_after_it_was_reported(self):
        self.assertEqual(uptime.plan([], [], T0), [])
        issue = {"number": 1, "title": uptime.TITLE, "createdAt": T0.isoformat(), "comments": []}
        failure = [{"path": "/", "status": 500}]
        self.assertEqual(uptime.plan(failure, [issue], T0 + timedelta(hours=1)), [])
        issue["comments"].append({"body": "still: 6 h - x"})
        self.assertEqual(uptime.plan(failure, [issue], T0 + timedelta(hours=11)), [])  # 6 h already reported


if __name__ == "__main__":
    unittest.main()
