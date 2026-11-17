"""ffprobe timeouts stay inside one advisor media item (scripts/advisor/media_job.py)."""
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts.advisor import media_job as mj

PROBE_OK = json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 4, 'height': 2}]}).encode()


def item(n):
    return {'id': n, 'sha256': 'abc', 'bytes': 3, 'r2_key': f'orig/{n}', 'keys': {'video': f'vid/{n}.mp4'}}


class FakeR2:
    def __init__(self):
        self.puts = []

    def head(self, key):
        return None

    def get_file(self, key, dest):
        dest.write_bytes(b'x')
        return True

    def put_file(self, key, path, meta, content_type=None):
        self.puts.append(key)


def make_run(probe_replies, probes=None):
    """A fake subprocess.run: ffprobe answers come from probe_replies; ffmpeg succeeds and writes its output."""
    replies = iter(probe_replies)

    def run(cmd, **kw):
        if cmd[0] == 'ffprobe':
            if probes is not None:
                probes.append((cmd, kw))
            reply = next(replies)
            if isinstance(reply, BaseException):
                raise reply
            return reply
        open(cmd[-1], 'wb').write(b'out')
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    return run


def timeout():
    return subprocess.TimeoutExpired(['ffprobe', 'secret-path'], 120)


def ok():
    return SimpleNamespace(returncode=0, stdout=PROBE_OK, stderr=b'')


def which(name):
    return name


class ProbeTimeoutTests(unittest.TestCase):
    def test_probe_timeout_is_unreadable(self):
        seen = []
        with self.assertRaises(mj.Unreadable) as ctx:
            mj.probe('ffprobe', 'secret-path', make_run([timeout()], seen))
        self.assertEqual(str(ctx.exception), 'probe-timeout')
        cmd, kw = seen[0]
        self.assertEqual(cmd, ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', 'secret-path'])
        self.assertEqual((kw['timeout'], kw['capture_output'], kw['check']), (120, True, False))

    def test_original_and_output_probe_timeout_never_upload(self):
        for stage, replies in (('original', [timeout()]), ('output', [ok(), timeout()])):
            with self.subTest(stage=stage):
                r2 = FakeR2()
                with self.assertRaises(mj.Unreadable) as ctx:
                    mj.derive_video(item(1), r2, log=lambda *_: None, which=which, run=make_run(replies))
                self.assertEqual(str(ctx.exception), 'probe-timeout')
                self.assertEqual(r2.puts, [])

    def test_probe_failure_controls(self):
        for reply in (SimpleNamespace(returncode=1, stdout=b'', stderr=b''),
                      SimpleNamespace(returncode=0, stdout=b'{not json', stderr=b'')):
            with self.assertRaises(mj.Unreadable) as ctx:
                mj.probe('ffprobe', 'p', make_run([reply]))
            self.assertEqual(str(ctx.exception), 'probe-failed')
        self.assertEqual(mj.probe('ffprobe', 'p', make_run([ok()])), json.loads(PROBE_OK))
        with self.assertRaises(RuntimeError):
            mj.probe('ffprobe', 'p', make_run([RuntimeError('boom')]))

    def test_job_continues_after_probe_timeout(self):
        done, r2 = [], FakeR2()
        api = SimpleNamespace(pending=lambda: {'videos': [item(1), item(2)]}, done=done.append)
        fake = make_run([timeout(), ok(), ok()])
        with mock.patch.object(mj.subprocess, 'run', fake), mock.patch.object(mj.shutil, 'which', which):
            counts = mj.run(api, r2, {}, 1, log=lambda *_: None)
        self.assertEqual((counts['failed'], counts['videos'], counts['transient']), (1, 1, 0))
        self.assertEqual(done[0], {'media_id': 1, 'error': 'probe-timeout'})
        self.assertEqual(done[1]['media_id'], 2)
        self.assertEqual(len(done), 2)
        self.assertEqual(r2.puts, ['vid/2.mp4'])


if __name__ == '__main__':
    unittest.main()
