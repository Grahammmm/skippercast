"""The advisor-media runner job (scripts/advisor/media_job.py, TA-M1).

The first half is standard library only and runs everywhere: SigV4 against
AWS's published test vectors, the R2 client and the Worker API client against
fake openers, and the job loop's error handling. The second half needs the
advisor extra (Pillow, pillow-heif) and skips cleanly without it: resize
bounds, no EXIF, sRGB, the Story footer band (pixel check of its colour), the
graphics rendered from fixture payloads, HEIC conversion and idempotence.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from scripts.advisor import media_job as mj

try:
    from PIL import Image, ImageCms, ImageDraw
    import pillow_heif
    HAVE_PILLOW = True
except ImportError:
    HAVE_PILLOW = False
NO_PILLOW = 'Pillow and pillow-heif are not installed (pip install -e ".[advisor]")'
HAVE_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
NO_FFMPEG = 'ffmpeg and ffprobe are not installed (the advisor media runner needs them; docs/operations/runners.md)'

EMPTY = hashlib.sha256(b'').hexdigest()


class Response:
    def __init__(self, status=200, body=b'', headers=None):
        self.status, self._body, self.headers = status, body, headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeR2:
    """The R2 client's interface over a dict, counting writes."""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.puts = []

    def get(self, key):
        found = self.objects.get(key)
        return found[0] if found else None

    def head(self, key):
        found = self.objects.get(key)
        return {k: str(v) for k, v in found[1].items()} if found else None

    def put(self, key, body, metadata, content_type='image/jpeg'):
        self.puts.append(key)
        self.objects[key] = (body, {k: str(v) for k, v in metadata.items()})
        self.types = {**getattr(self, 'types', {}), key: content_type}

    def get_file(self, key, path):
        found = self.objects.get(key)
        if not found:
            return False
        with open(path, 'wb') as out:
            out.write(found[0])
        return True

    def put_file(self, key, path, metadata, content_type='video/mp4'):
        with open(path, 'rb') as handle:
            self.put(key, handle.read(), metadata, content_type)


class FakeApi:
    def __init__(self, pages):
        self.pages, self.reports = list(pages), []

    def pending(self):
        return self.pages.pop(0) if self.pages else {'media': [], 'graphics': []}

    def done(self, payload):
        self.reports.append(payload)
        return {'ok': True}


def keys(media_id):
    return {'public': f'advisor/derived/{media_id}/public.jpg', 'thumb': f'advisor/derived/{media_id}/thumb.jpg',
            'story': f'advisor/derived/{media_id}/story.jpg'}


class SigV4Tests(unittest.TestCase):
    def test_aws_get_vanilla_vector(self):
        # AWS Signature Version 4 test suite, "get-vanilla".
        headers = mj.sign_v4('GET', 'https://example.amazonaws.com/', {}, EMPTY, 'AKIDEXAMPLE',
                             'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY', datetime(2015, 8, 30, 12, 36, tzinfo=timezone.utc),
                             region='us-east-1', service='service')
        self.assertEqual(headers['authorization'],
                         'AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, '
                         'SignedHeaders=host;x-amz-date, Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31')
        self.assertEqual(headers['x-amz-date'], '20150830T123600Z')

    def test_aws_s3_get_object_example(self):
        # Amazon S3 API reference, "Example: GET Object" (header-based SigV4).
        headers = mj.sign_v4('GET', 'https://examplebucket.s3.amazonaws.com/test.txt',
                             {'Range': 'bytes=0-9', 'x-amz-content-sha256': EMPTY}, EMPTY, 'AKIAIOSFODNN7EXAMPLE',
                             'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY', datetime(2013, 5, 24, tzinfo=timezone.utc), region='us-east-1')
        self.assertTrue(headers['authorization'].endswith(
            'SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, '
            'Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'))


class R2ClientTests(unittest.TestCase):
    def client(self, respond):
        self.requests = []

        def opener(request, timeout):
            self.requests.append(request)
            return respond(request)
        return mj.R2('acct', 'KEY', 'SECRET', opener=opener, clock=lambda: datetime(2026, 10, 4, 15, tzinfo=timezone.utc))

    def test_put_signs_the_body_and_sends_metadata(self):
        r2 = self.client(lambda request: Response(200))
        r2.put('advisor/derived/m 1/public.jpg', b'jpeg', {'source-sha256': 'abc', 'width': 10})
        request = self.requests[0]
        self.assertEqual(request.full_url, 'https://acct.r2.cloudflarestorage.com/skippercast-advisor-media/advisor/derived/m%201/public.jpg')
        self.assertEqual(request.get_method(), 'PUT')
        self.assertEqual(request.data, b'jpeg')
        sent = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(sent['x-amz-content-sha256'], hashlib.sha256(b'jpeg').hexdigest())
        self.assertEqual((sent['x-amz-meta-source-sha256'], sent['x-amz-meta-width'], sent['content-type']), ('abc', '10', 'image/jpeg'))
        self.assertIn('SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date;x-amz-meta-source-sha256;x-amz-meta-width',
                      sent['authorization'])
        self.assertIn('Credential=KEY/20261004/auto/s3/aws4_request', sent['authorization'])

    def test_missing_objects_are_none_and_metadata_comes_back_without_its_prefix(self):
        def respond(request):
            if request.full_url.endswith('/missing.jpg'):
                raise HTTPError(request.full_url, 404, 'Not Found', {}, None)
            return Response(200, b'body', {'X-Amz-Meta-Source-Sha256': 'abc', 'Content-Type': 'image/jpeg'})
        r2 = self.client(respond)
        self.assertIsNone(r2.get('missing.jpg'))
        self.assertIsNone(r2.head('missing.jpg'))
        self.assertEqual(r2.get('there.jpg'), b'body')
        self.assertEqual(r2.head('there.jpg'), {'source-sha256': 'abc'})
        self.assertEqual(self.requests[-1].get_method(), 'HEAD')

    def test_other_failures_are_transient(self):
        def respond(request):
            raise HTTPError(request.full_url, 503, 'Busy', {}, None)
        with self.assertRaises(mj.Transient):
            self.client(respond).get('x.jpg')
        with self.assertRaises(mj.Transient):
            self.client(lambda request: (_ for _ in ()).throw(TimeoutError())).put('x.jpg', b'x', {})


class ApiClientTests(unittest.TestCase):
    def test_requests_carry_a_fresh_token_and_a_named_client(self):
        seen, now, tokens = [], [0.0], iter(['t1', 't2'])

        def opener(request, timeout):
            seen.append(request)
            return Response(200, b'{"media": [], "graphics": []}')
        api = mj.Api('https://skippercast.com/', 'https://skippercast.com/api/advisor/jobs', opener=opener,
                     token_source=lambda: next(tokens), clock=lambda: now[0])
        self.assertEqual(api.pending(), {'media': [], 'graphics': []})
        api.done({'media_id': 'm1', 'error': 'x'})
        now[0] = 300.0
        api.pending()
        self.assertEqual([r.full_url for r in seen], ['https://skippercast.com/api/advisor/jobs/media',
                                                       'https://skippercast.com/api/advisor/jobs/media-done',
                                                       'https://skippercast.com/api/advisor/jobs/media'])
        self.assertEqual([r.get_header('Authorization') for r in seen], ['Bearer t1', 'Bearer t1', 'Bearer t2'])
        self.assertEqual(json.loads(seen[1].data), {'media_id': 'm1', 'error': 'x'})
        self.assertTrue(seen[0].get_header('User-agent').startswith('SkipperCast-advisor-media/'))

    def test_the_oidc_token_is_requested_for_the_advisor_audience(self):
        seen = []

        def opener(request, timeout):
            seen.append(request)
            return Response(200, b'{"value": "oidc"}')
        env = {'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://token.example/req?api-version=2.0', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'rt'}
        with mock.patch.dict('os.environ', env):
            api = mj.Api('https://skippercast.com', 'https://skippercast.com/api/advisor/jobs', opener=opener)
            self.assertEqual(api.token(), 'oidc')
        self.assertEqual(parse_qs(urlsplit(seen[0].full_url).query)['audience'], ['https://skippercast.com/api/advisor/jobs'])
        self.assertEqual(seen[0].get_header('Authorization'), 'Bearer rt')

    def test_http_errors_are_transient(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, 'Unauthorized', {}, None)
        api = mj.Api('https://skippercast.com', 'aud', opener=opener, token_source=lambda: 't')
        with self.assertRaises(mj.Transient):
            api.pending()


class JobLoopTests(unittest.TestCase):
    def test_a_missing_original_is_given_up_and_a_transient_error_is_retried_next_run(self):
        class Flaky(FakeR2):
            def head(self, key):
                if 'flaky' in key:
                    raise mj.Transient('R2 HEAD HTTP 503')
                return super().head(key)
        item = {'id': 'gone', 'r2_key': 'advisor/media/c1/gone.jpg', 'mime': 'image/jpeg', 'sha256': 'a', 'bytes': 1, 'keys': keys('gone')}
        flaky = {**item, 'id': 'flaky', 'keys': keys('flaky')}
        api = FakeApi([{'media': [item, flaky], 'graphics': []}, {'media': [flaky], 'graphics': []}])
        lines = []
        counts = mj.run(api, Flaky(), {}, None, log=lines.append)
        self.assertEqual(api.reports, [{'media_id': 'gone', 'error': 'original-missing'}])
        self.assertEqual(counts, {'media': 0, 'graphics': 0, 'videos': 0, 'failed': 1, 'transient': 1})
        self.assertTrue(any('retry later' in line for line in lines))

    def test_display_number(self):
        self.assertEqual(mj.display_number('+18055550100'), '(805) 555-0100')
        self.assertEqual(mj.display_number('8055550100'), '(805) 555-0100')
        self.assertIsNone(mj.display_number(''))
        self.assertIsNone(mj.display_number(None))

    def test_the_graphic_digest_changes_with_its_inputs(self):
        base = {'kind': 'daily', 'data': {'port': 'Morro Bay'}, 'media': []}
        self.assertEqual(mj.request_digest(base), mj.request_digest({**base, 'id': 'other', 'out_key': 'x'}))
        self.assertNotEqual(mj.request_digest(base), mj.request_digest({**base, 'data': {'port': 'Avila'}}))
        self.assertNotEqual(mj.request_digest(base), mj.request_digest({**base, 'media': [{'id': 'm1'}]}))

    def test_the_layout_spec_names_every_box_the_job_draws(self):
        spec = mj.load_spec()
        self.assertEqual(spec['story']['size'], [1080, 1920])
        self.assertEqual((spec['public']['max_side'], spec['public']['quality'], spec['thumb']['max_side']), (1440, 88, 320))
        self.assertEqual(spec['footer']['text'], 'Text SkipperCast')
        for layout in ('story', 'daily', 'roundup'):
            width, height = spec[layout]['size']
            for name, box in spec[layout].items():
                if name.endswith('_box'):
                    left, top, right, bottom = box
                    self.assertTrue(0 <= left < right <= width and 0 <= top < bottom <= height, f'{layout}.{name}')
            self.assertEqual(spec[layout]['band_box'][3], height, f'{layout}: the band is at the bottom')


# ---- video metadata (00 principle 7) -------------------------------------------------------

def box(kind, payload=b''):
    kind = kind if isinstance(kind, bytes) else kind.encode('latin-1')
    return (8 + len(payload)).to_bytes(4, 'big') + kind + payload


def mp4(*moov_children, mdat=b'\0' * 16):
    """A minimal ISO-BMFF file: ftyp, moov with the given children (after an mvhd), mdat."""
    return box('ftyp', b'isom\0\0\x02\0isomiso2mp41') + box('moov', box('mvhd', b'\0' * 100) + b''.join(moov_children)) + box('mdat', mdat)


# A QuickTime udta location atom as an iPhone writes it: ©xyz, a 16-bit length, a 16-bit language, ISO 6709 text.
XYZ = box(b'\xa9xyz', len(b'+35.3658-120.8499/').to_bytes(2, 'big') + b'\x15\xc7' + b'+35.3658-120.8499/')


class VideoMetadataTests(unittest.TestCase):
    def test_a_udta_xyz_atom_is_found_and_a_clean_file_is_clean(self):
        self.assertEqual(mj.location_atoms(mp4(box('udta', XYZ))), ['xyz-atom'])
        self.assertEqual(mj.location_atoms(mp4(box('trak', box('udta', XYZ)))), ['xyz-atom'], 'inside a track too')
        self.assertEqual(mj.location_atoms(mp4(box('udta', box('name', b'clip')))), [])
        self.assertEqual(mj.location_atoms(mp4()), [])

    def test_quicktime_keys_naming_the_location_and_a_3gpp_loci_atom_are_found(self):
        keys_box = box('keys', b'\0\0\0\0' + (1).to_bytes(4, 'big') + box('mdta', b'com.apple.quicktime.location.ISO6709'))
        quicktime_meta = box('meta', box('hdlr', b'\0' * 24) + keys_box + box('ilst', b''))
        self.assertEqual(mj.location_atoms(mp4(quicktime_meta)), ['keys-location'])
        iso_meta = box('meta', b'\0\0\0\0' + box('hdlr', b'\0' * 24) + keys_box)   # a full box (version, flags)
        self.assertEqual(mj.location_atoms(mp4(box('udta', iso_meta))), ['keys-location'])
        self.assertEqual(mj.location_atoms(mp4(box('udta', box('loci', b'\0' * 20)))), ['loci-atom'])

    def test_samples_are_not_read_and_malformed_boxes_never_raise(self):
        self.assertEqual(mj.location_atoms(mp4(mdat=b'com.apple.quicktime.location.ISO6709')), [], 'mdat holds samples, not metadata')
        for broken in (b'', b'\0\0\0', box('moov')[:-1] + b'\xff' * 3, (2 ** 31).to_bytes(4, 'big') + b'moov' + XYZ, mp4(box('udta', XYZ))[:40]):
            mj.location_atoms(broken)

    def test_the_file_walk_skips_mdat_and_reads_every_other_top_level_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirty, clean = os.path.join(tmp, 'dirty.mp4'), os.path.join(tmp, 'clean.mp4')
            with open(dirty, 'wb') as handle:
                handle.write(mp4(box('udta', XYZ)) + box('udta', XYZ))
            with open(clean, 'wb') as handle:
                handle.write(mp4(mdat=XYZ * 4))
            self.assertEqual(mj.file_location_atoms(dirty), ['xyz-atom'])
            self.assertEqual(mj.file_location_atoms(clean), [])

    def test_location_tags_reads_ffprobe_format_and_stream_tags(self):
        probe_json = {'format': {'tags': {'major_brand': 'isom', 'location': '+35.3658-120.8499/', 'com.apple.quicktime.location.ISO6709': 'x'}},
                      'streams': [{'tags': {'handler_name': 'VideoHandler'}}, {'tags': {'location-eng': 'x'}}]}
        self.assertEqual(mj.location_tags(probe_json), ['format:location', 'format:com.apple.quicktime.location.ISO6709', 'stream1:location-eng'])
        self.assertEqual(mj.location_tags({'format': {'tags': {'encoder': 'Lavf'}}, 'streams': []}), [])
        self.assertEqual(mj.location_tags(None), [])

    def test_the_strip_command_copies_streams_without_any_metadata(self):
        command = mj.strip_command('ffmpeg', 'in.mov', 'out.mp4')
        for flag in (['-map_metadata', '-1'], ['-map_metadata:s', '-1'], ['-map_chapters', '-1'], ['-c', 'copy'], ['-movflags', '+faststart'], ['-f', 'mp4']):
            self.assertTrue(any(command[i:i + 2] == flag for i in range(len(command))), flag)
        self.assertIn('-dn', command)
        self.assertNotIn('-tag:v', command)
        hevc = mj.strip_command('ffmpeg', 'a', 'b', hevc=True)
        self.assertEqual(hevc[hevc.index('-tag:v') + 1], 'hvc1')

    def test_without_ffmpeg_the_video_is_reported_no_ffmpeg(self):
        item = {'id': 'v1', 'r2_key': 'advisor/media/c1/v1.mov', 'mime': 'video/quicktime', 'sha256': 'a', 'bytes': 3, 'keys': {'video': 'advisor/derived/v1/video.mp4'}}
        r2 = FakeR2({item['r2_key']: (b'mov', {})})
        with self.assertRaises(mj.Unreadable) as raised:
            mj.derive_video(item, r2, log=lambda *_: None, which=lambda _: None)
        self.assertEqual(str(raised.exception), 'no-ffmpeg')
        api = FakeApi([{'media': [], 'graphics': [], 'videos': [item]}])
        with mock.patch.object(mj.shutil, 'which', return_value=None):
            counts = mj.run(api, r2, {}, None, log=lambda *_: None)
        self.assertEqual(api.reports, [{'media_id': 'v1', 'error': 'no-ffmpeg'}])
        self.assertEqual(counts, {'media': 0, 'graphics': 0, 'videos': 0, 'failed': 1, 'transient': 0})
        self.assertEqual(r2.puts, [], 'nothing uploaded')


def ffmpeg_clip(path, *metadata):
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=64x48:rate=10',
                    '-f', 'lavfi', '-i', 'sine=duration=1', '-shortest', '-c:v', 'mpeg4', '-c:a', 'aac', *metadata, str(path)], check=True)


@unittest.skipUnless(HAVE_FFMPEG, NO_FFMPEG)
class VideoStripTests(unittest.TestCase):
    def strip(self, *metadata, name='in.mov'):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, name)
            ffmpeg_clip(source, *metadata)
            with open(source, 'rb') as handle:
                original = handle.read()
        item = {'id': 'v1', 'r2_key': 'advisor/media/c1/v1.mov', 'mime': 'video/quicktime', 'sha256': hashlib.sha256(original).hexdigest(),
                'bytes': len(original), 'keys': {'video': 'advisor/derived/v1/video.mp4'}}
        r2 = FakeR2({item['r2_key']: (original, {})})
        return mj.derive_video(item, r2, log=lambda *_: None), r2, item, original

    def check_clean(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.mp4')
            with open(path, 'wb') as handle:
                handle.write(data)
            self.assertEqual(mj.file_location_atoms(path), [])
            probed = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path],
                                               capture_output=True, check=True).stdout)
            self.assertEqual(mj.location_tags(probed), [])
            self.assertNotIn(b'+35.3658-120.8499', data)
            return probed

    def test_a_udta_location_atom_is_removed_and_the_streams_are_kept(self):
        payload, r2, item, original = self.strip('-metadata', 'location=+35.3658-120.8499/')
        self.assertIn('xyz-atom', mj.location_atoms(original), 'the fixture carries the atom')
        self.assertEqual(payload, {'media_id': 'v1', 'keys': {'video': 'advisor/derived/v1/video.mp4'}, 'width': 64, 'height': 48})
        stripped, meta = r2.objects['advisor/derived/v1/video.mp4']
        self.assertEqual((meta['source-sha256'], meta['stripped'], r2.types['advisor/derived/v1/video.mp4']), (item['sha256'], '1', 'video/mp4'))
        probed = self.check_clean(stripped)
        self.assertEqual(sorted(s['codec_type'] for s in probed['streams']), ['audio', 'video'])
        # A rerun on the same original copies nothing.
        mj.derive_video(item, r2, log=lambda *_: None)
        self.assertEqual(r2.puts, ['advisor/derived/v1/video.mp4'])

    def test_a_quicktime_keys_location_is_removed(self):
        _, r2, _, original = self.strip('-movflags', 'use_metadata_tags', '-metadata', 'com.apple.quicktime.location.ISO6709=+35.3658-120.8499/')
        self.assertIn('keys-location', mj.location_atoms(original))
        self.check_clean(r2.objects['advisor/derived/v1/video.mp4'][0])

    def test_a_file_ffprobe_cannot_read_is_given_up(self):
        item = {'id': 'v2', 'r2_key': 'advisor/media/c1/v2.mp4', 'mime': 'video/mp4', 'sha256': 'b', 'bytes': 9, 'keys': {'video': 'advisor/derived/v2/video.mp4'}}
        with self.assertRaises(mj.Unreadable) as raised:
            mj.derive_video(item, FakeR2({item['r2_key']: (b'not a video at all', {})}), log=lambda *_: None)
        self.assertEqual(str(raised.exception), 'probe-failed')


def photo_bytes(size=(4032, 3024), fmt='JPEG', **save):
    image = Image.new('RGB', size, (200, 120, 40))
    ImageDraw.Draw(image).ellipse((size[0] // 4, size[1] // 4, 3 * size[0] // 4, 3 * size[1] // 4), fill=(30, 90, 160))
    buffer = io.BytesIO()
    if fmt == 'HEIC':
        pillow_heif.from_pillow(image).save(buffer, quality=90)
    else:
        image.save(buffer, fmt, **save)
    return buffer.getvalue()


def pixels(image):
    return image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()


def near(pixel, color, tolerance=8):
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, color))


@unittest.skipUnless(HAVE_PILLOW, NO_PILLOW)
class DerivedImageTests(unittest.TestCase):
    def setUp(self):
        self.spec = mj.load_spec()

    def derive(self, data, mime='image/jpeg', media_id='m1', r2=None):
        r2 = r2 or FakeR2()
        r2.objects[f'advisor/media/c1/{media_id}'] = (data, {})
        item = {'id': media_id, 'r2_key': f'advisor/media/c1/{media_id}', 'mime': mime, 'sha256': hashlib.sha256(data).hexdigest(),
                'bytes': len(data), 'keys': keys(media_id)}
        return mj.derive_media(item, r2, self.spec, '+18055550100', log=lambda *_: None), r2, item

    def image(self, r2, key):
        return Image.open(io.BytesIO(r2.objects[key][0]))

    def test_public_and_thumb_stay_within_their_bounds_and_carry_no_exif(self):
        exif = Image.Exif()
        exif[0x010F] = 'CameraMaker'
        payload, r2, _ = self.derive(photo_bytes(exif=exif.tobytes()))
        self.assertEqual((payload['width'], payload['height'], payload['source_width'], payload['source_height']), (1440, 1080, 4032, 3024))
        public, thumb, story = (self.image(r2, k) for k in keys('m1').values())
        self.assertEqual((public.size, thumb.size, story.size), ((1440, 1080), (320, 240), (1080, 1920)))
        for image in (public, thumb, story):
            self.assertEqual(image.format, 'JPEG')
            self.assertNotIn('exif', image.info)
            self.assertEqual(len(image.getexif()), 0)
            self.assertNotIn('icc_profile', image.info)
        self.assertEqual(r2.objects[keys('m1')['public']][1]['source-sha256'], hashlib.sha256(r2.objects['advisor/media/c1/m1'][0]).hexdigest())

    def test_a_small_photo_is_never_enlarged_and_a_portrait_keeps_its_long_side(self):
        payload, _, _ = self.derive(photo_bytes((800, 600)))
        self.assertEqual((payload['width'], payload['height']), (800, 600))
        payload, _, _ = self.derive(photo_bytes((3000, 4000)), media_id='m2')
        self.assertEqual((payload['width'], payload['height']), (1080, 1440))

    def test_an_embedded_colour_profile_is_applied_and_dropped(self):
        # ImageCms can only build sRGB, LAB and XYZ profiles, so this proves the path, not a P3 shift.
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        _, r2, _ = self.derive(photo_bytes((400, 300), icc_profile=srgb))
        public = self.image(r2, keys('m1')['public'])
        self.assertNotIn('icc_profile', public.info, 'plain sRGB out')
        self.assertEqual(public.mode, 'RGB')
        self.assertTrue(near(public.getpixel((5, 5)), (200, 120, 40), 10), 'colours survive the conversion')

    def test_the_story_has_the_footer_band_with_its_text_and_the_photo_above(self):
        _, r2, _ = self.derive(photo_bytes())
        story = self.image(r2, keys('m1')['story']).convert('RGB')
        band, text = tuple(self.spec['colors']['band']), tuple(self.spec['colors']['band_text'])
        left, top, right, bottom = self.spec['story']['band_box']
        self.assertTrue(near(story.getpixel((left + 10, bottom - 10)), band), 'band colour at the bottom-left corner')
        self.assertTrue(near(story.getpixel((right - 10, top + 10)), band), 'band colour at its top-right corner')
        strip = story.crop((left, top, right, bottom))
        bright = sum(1 for p in pixels(strip) if near(p, text, 40))
        self.assertGreater(bright, 500, 'the footer text is drawn in the band')
        self.assertTrue(near(story.getpixel((540, 840)), (30, 90, 160), 12), 'the photo sits centred above the band')
        self.assertTrue(near(story.getpixel((540, 40)), tuple(self.spec['colors']['field']), 8), 'on the dark field')

    def test_the_footer_shows_the_fallback_without_a_number(self):
        with_number = mj.story_image(self.spec, None, '+18055550100')
        without = mj.story_image(self.spec, None, None)
        box = self.spec['story']['band_box']
        self.assertNotEqual(with_number.crop(box).tobytes(), without.crop(box).tobytes())

    def test_heic_is_converted_to_jpeg(self):
        payload, r2, _ = self.derive(photo_bytes((1600, 1200), fmt='HEIC'), mime='image/heic')
        self.assertEqual((payload['width'], payload['height'], payload['source_width']), (1440, 1080, 1600))
        self.assertEqual(self.image(r2, keys('m1')['public']).format, 'JPEG')

    def test_an_unreadable_original_is_given_up(self):
        with self.assertRaises(mj.Unreadable) as raised:
            self.derive(b'\xff\xd8\xff not really a jpeg')
        self.assertTrue(str(raised.exception).startswith('decode-failed'))

    def test_idempotent_the_same_source_is_not_rendered_twice_and_a_new_one_is(self):
        first, r2, item = self.derive(photo_bytes((2000, 1500)))
        self.assertEqual(len(r2.puts), 3)
        again = mj.derive_media(item, r2, self.spec, '+18055550100', log=lambda *_: None)
        self.assertEqual(again, first)
        self.assertEqual(len(r2.puts), 3, 'nothing re-uploaded')
        mj.derive_media({**item, 'sha256': 'changed'}, r2, self.spec, '+18055550100', log=lambda *_: None)
        self.assertEqual(len(r2.puts), 6, 'a different source sha renders again')

    def test_the_job_loop_reports_each_item_once(self):
        data = photo_bytes((900, 600))
        r2 = FakeR2({'advisor/media/c1/m1': (data, {})})
        item = {'id': 'm1', 'r2_key': 'advisor/media/c1/m1', 'mime': 'image/jpeg', 'sha256': 's', 'bytes': len(data), 'keys': keys('m1')}
        api = FakeApi([{'media': [item], 'graphics': []}, {'media': [item], 'graphics': []}])
        counts = mj.run(api, r2, self.spec, None, log=lambda *_: None)
        self.assertEqual(counts, {'media': 1, 'graphics': 0, 'videos': 0, 'failed': 0, 'transient': 0})
        self.assertEqual(api.reports, [{'media_id': 'm1', 'keys': keys('m1'), 'width': 900, 'height': 600, 'source_width': 900, 'source_height': 600}])


def stored_as(upright_image, orientation):
    """How a camera stores `upright_image` with this EXIF orientation, from the EXIF definition of row 0 and column 0.

    Written independently of Pillow's transpose table: 1 row 0 = top, column 0 = left;
    2 top/right; 3 bottom/right; 4 bottom/left; 5 left/top; 6 right/top; 7 right/bottom; 8 left/bottom.
    """
    w, h = upright_image.size
    u = lambda row, col: upright_image.getpixel((col, row))
    source = {
        1: lambda r, c: u(r, c), 2: lambda r, c: u(r, w - 1 - c), 3: lambda r, c: u(h - 1 - r, w - 1 - c), 4: lambda r, c: u(h - 1 - r, c),
        5: lambda r, c: u(c, r), 6: lambda r, c: u(c, w - 1 - r), 7: lambda r, c: u(h - 1 - c, w - 1 - r), 8: lambda r, c: u(h - 1 - c, r),
    }[orientation]
    sw, sh = (w, h) if orientation <= 4 else (h, w)
    stored = Image.new('RGB', (sw, sh))
    for r in range(sh):
        for c in range(sw):
            stored.putpixel((c, r), source(r, c))
    return stored


@unittest.skipUnless(HAVE_PILLOW, NO_PILLOW)
class OrientationTests(unittest.TestCase):
    """The Worker strips a JPEG's EXIF and passes its Orientation in the work list; the job turns the pixels upright."""

    UPRIGHT = [(10, 0, 0), (20, 0, 0), (30, 0, 0), (0, 40, 0), (0, 50, 0), (0, 60, 0)]   # 3 x 2, every pixel distinct

    def upright_image(self):
        image = Image.new('RGB', (3, 2))
        image.putdata(self.UPRIGHT)
        return image

    def test_each_of_the_eight_orientations_comes_out_upright(self):
        reference = self.upright_image()
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                stored = stored_as(reference, orientation)
                self.assertEqual(stored.size, (3, 2) if orientation <= 4 else (2, 3))
                turned = mj.upright(stored, orientation)
                self.assertEqual(turned.size, (3, 2))
                self.assertEqual(list(pixels(turned)), self.UPRIGHT)

    def test_an_unknown_or_missing_orientation_leaves_the_pixels_alone(self):
        stored = stored_as(self.upright_image(), 6)
        for value in (None, 0, 9, '6', True):
            with self.subTest(value=value):
                self.assertEqual(mj.upright(stored, value).tobytes(), stored.tobytes())

    def test_a_stripped_sideways_jpeg_is_derived_upright_and_the_value_is_recorded(self):
        # The original as stored by the Worker: landscape pixels, no EXIF, orientation 6 on the row.
        portrait = Image.new('RGB', (300, 400), (200, 120, 40))
        ImageDraw.Draw(portrait).rectangle((0, 0, 299, 49), fill=(30, 90, 160))       # a blue band along the top
        buffer = io.BytesIO()
        stored_as(portrait, 6).save(buffer, 'JPEG', quality=95)
        data = buffer.getvalue()
        r2 = FakeR2({'advisor/media/c1/m6': (data, {})})
        item = {'id': 'm6', 'r2_key': 'advisor/media/c1/m6', 'mime': 'image/jpeg', 'sha256': 's6', 'bytes': len(data), 'orientation': 6, 'keys': keys('m6')}
        payload = mj.derive_media(item, r2, mj.load_spec(), None, log=lambda *_: None)
        self.assertEqual((payload['width'], payload['height'], payload['source_width'], payload['source_height']), (300, 400, 300, 400))
        public = Image.open(io.BytesIO(r2.objects[keys('m6')['public']][0])).convert('RGB')
        self.assertTrue(near(public.getpixel((150, 10)), (30, 90, 160), 12), 'the band is at the top again')
        self.assertTrue(near(public.getpixel((150, 390)), (200, 120, 40), 12))
        self.assertEqual(r2.objects[keys('m6')['public']][1]['orientation'], '6')
        # Unchanged: skipped. The same bytes derived earlier without the value (files from before) render again.
        mj.derive_media(item, r2, mj.load_spec(), None, log=lambda *_: None)
        self.assertEqual(len(r2.puts), 3)
        for key in keys('m6').values():
            r2.objects[key][1].pop('orientation')
        mj.derive_media(item, r2, mj.load_spec(), None, log=lambda *_: None)
        self.assertEqual(len(r2.puts), 6)


@unittest.skipUnless(HAVE_PILLOW, NO_PILLOW)
class GraphicTests(unittest.TestCase):
    DAILY = {'id': 'g1', 'kind': 'daily', 'out_key': 'advisor/posts/p1/daily.jpg', 'media': [],
             'data': {'port': 'Morro Bay', 'date': 'Sat Oct 3', 'lines': [{'label': 'Rockfish', 'value': 'limits for 22 anglers'},
                                                                          {'label': 'Lingcod', 'value': 14}],
                      'conditions': 'Wind 8 kt NW', 'confidence': 'Good'}}

    def setUp(self):
        self.spec = mj.load_spec()

    def test_the_daily_graphic_renders_from_a_fixture_payload(self):
        r2 = FakeR2()
        payload = mj.render_graphic(self.DAILY, r2, self.spec, '+18055550100', log=lambda *_: None)
        self.assertEqual(payload, {'graphic_id': 'g1', 'keys': {'public': 'advisor/posts/p1/daily.jpg'}, 'width': 1080, 'height': 1350})
        image = Image.open(io.BytesIO(r2.objects['advisor/posts/p1/daily.jpg'][0])).convert('RGB')
        self.assertEqual(image.size, (1080, 1350))
        self.assertTrue(near(image.getpixel((10, 1340)), tuple(self.spec['colors']['band'])))
        lines = image.crop(tuple(self.spec['daily']['lines_box']))
        self.assertGreater(sum(1 for p in pixels(lines) if near(p, (255, 255, 255), 40)), 500, 'the lines are drawn')
        title = image.crop(tuple(self.spec['daily']['title_box']))
        self.assertGreater(sum(1 for p in pixels(title) if near(p, tuple(self.spec['colors']['accent']), 40)), 300, 'the title is drawn')
        # Unchanged request: skipped; changed data: rendered again.
        mj.render_graphic(self.DAILY, r2, self.spec, '+18055550100', log=lambda *_: None)
        self.assertEqual(r2.puts, ['advisor/posts/p1/daily.jpg'])
        mj.render_graphic({**self.DAILY, 'data': {**self.DAILY['data'], 'date': 'Sun Oct 4'}}, r2, self.spec, None, log=lambda *_: None)
        self.assertEqual(len(r2.puts), 2)

    def test_a_story_card_and_a_roundup_with_slides(self):
        data = photo_bytes((1200, 900))
        r2 = FakeR2({'advisor/media/c1/m1.jpg': (data, {})})
        source = {'id': 'm1', 'r2_key': 'advisor/media/c1/m1.jpg', 'mime': 'image/jpeg', 'public_key': 'advisor/derived/m1/public.jpg'}
        story = mj.render_graphic({'id': 's1', 'kind': 'story', 'out_key': 'advisor/posts/s1/story.jpg', 'media': [source],
                                   'data': {'title': 'Today', 'lines': ['Rockfish: limits']}}, r2, self.spec, None, log=lambda *_: None)
        self.assertEqual((story['width'], story['height']), (1080, 1920))
        roundup = mj.render_graphic({'id': 'r1', 'kind': 'roundup', 'out_key': 'advisor/posts/w1/roundup.jpg', 'media': [source, source],
                                     'data': {'title': 'This week', 'lines': [{'label': 'Morro Bay', 'value': 'limits'}],
                                              'captions': ['Aboard Rita G']}}, r2, self.spec, None, log=lambda *_: None)
        self.assertEqual(roundup['keys'], {'public': 'advisor/posts/w1/roundup.jpg',
                                           'slides': ['advisor/posts/w1/roundup-1.jpg', 'advisor/posts/w1/roundup-2.jpg']})
        for key in ('advisor/posts/w1/roundup.jpg', *roundup['keys']['slides']):
            self.assertEqual(Image.open(io.BytesIO(r2.objects[key][0])).size, (1080, 1350), key)
        again = mj.render_graphic({'id': 'r1', 'kind': 'roundup', 'out_key': 'advisor/posts/w1/roundup.jpg', 'media': [source, source],
                                   'data': {'title': 'This week', 'lines': [{'label': 'Morro Bay', 'value': 'limits'}],
                                            'captions': ['Aboard Rita G']}}, r2, self.spec, None, log=lambda *_: None)
        self.assertEqual(again, roundup, 'a rerun reports the same keys without rendering')


if __name__ == '__main__':
    unittest.main()
