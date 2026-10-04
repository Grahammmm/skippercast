#!/usr/bin/env python3
"""Derive the Text Advisor's public images and render its graphics (TA-M1).

    python scripts/advisor/media_job.py [--max-rounds 20]

Run by .github/workflows/advisor-media.yml on the self-hosted runner, which the
Worker dispatches whenever media or a graphic becomes pending
(docs/plans/text-advisor/09-social.md § Derived images and graphics):

1. GET <ADVISOR_PUBLIC_BASE>/api/advisor/jobs/media with a GitHub Actions OIDC
   token requested for the audience <public_origin>/api/advisor/jobs
   (deployments/production.json; server/job-auth.ts accepts it only from
   advisor-media.yml).
2. For each media item: download the original from the private R2 bucket
   skippercast-advisor-media over the S3 API (SigV4 in the standard library;
   credentials derived from R2_ADVISOR_TOKEN the way scripts/publish_r2.py
   derives them), decode it (HEIC through pillow-heif), turn it upright (a JPEG
   by the EXIF orientation the Worker read before stripping it, passed in the
   work list; anything else by its own EXIF), convert to sRGB and write
   advisor/derived/<id>/public.jpg (at most 1440 px on the long side, quality
   88, no EXIF), thumb.jpg (320 px) and story.jpg (1080 x 1920, the photo on the
   dark field above a "Text SkipperCast" band with ADVISOR_NUMBER).
3. For each graphic request (daily, story, roundup): render it from its data
   and catalog/advisor/graphics.json to its out_key.
4. For each video (every stored video, private ones too, so it is clean before
   anyone reviews it): copy its streams without the container's metadata with
   ffmpeg (`-map_metadata -1 -map_chapters -1 -c copy -movflags +faststart`, no
   data or subtitle tracks), so no udta/©xyz or keys/mdta location atom
   survives; check the result with ffprobe and an atom walk, and upload it to
   advisor/derived/<id>/video.mp4 (00 principle 7: a video never leaks a
   position). Without ffmpeg on the runner the video is reported 'no-ffmpeg'
   and its approval stays held.
5. POST /api/advisor/jobs/media-done for each item with the keys and sizes, or
   with `error` when the file cannot be decoded (the item is then given up).

Idempotent: every object carries x-amz-meta-source-sha256 (the original's
sha256, or a digest of the graphic request); an item whose files already exist
with the same value is reported done without decoding anything. Network and R2
errors leave the item pending for the next run and make this run exit 1.
Video is never transcoded (09): its streams are copied as they are.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ''):          # run as a file: make `scripts.publish_r2` importable
    sys.path.insert(0, str(ROOT))
from scripts.publish_r2 import token_id  # noqa: E402  (R2 S3 credentials from an API token)

GRAPHICS = ROOT / 'catalog' / 'advisor' / 'graphics.json'
DEPLOYMENT = ROOT / 'deployments' / 'production.json'
BUCKET = 'skippercast-advisor-media'
META = 'source-sha256'
EMPTY_SHA = hashlib.sha256(b'').hexdigest()
HEIF = ('image/heic', 'image/heif')


class Transient(Exception):
    """Network, R2 or API trouble: the item stays pending for the next run."""


class Unreadable(Exception):
    """The original cannot be decoded: the item is reported with `error` and given up."""


# ---- AWS Signature Version 4 (stdlib) ---------------------------------------------

def _hmac(key, text):
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def _uri(path):
    return quote(path or '/', safe='/-_.~')


def sign_v4(method, url, headers, payload_sha, access_key, secret_key, now, region='auto', service='s3'):
    """The Authorization header and the headers to send with it, signing every header given plus host and x-amz-date.

    `url`'s path must already be percent-encoded (S3 paths are encoded once, not twice).
    """
    parts = urlsplit(url)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    day = amz_date[:8]
    signed = {k.lower(): ' '.join(str(v).strip().split()) for k, v in headers.items()}
    signed['host'] = parts.netloc
    signed['x-amz-date'] = amz_date
    names = sorted(signed)
    query = '&'.join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
                     for k, v in sorted(parse_qsl(parts.query, keep_blank_values=True)))
    canonical = '\n'.join([method, parts.path or '/', query, ''.join(f'{n}:{signed[n]}\n' for n in names),
                           ';'.join(names), payload_sha])
    scope = f'{day}/{region}/{service}/aws4_request'
    to_sign = '\n'.join(['AWS4-HMAC-SHA256', amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(('AWS4' + secret_key).encode(), day), region), service), 'aws4_request')
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in signed.items() if k != 'host'}
    out['authorization'] = f'AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={";".join(names)}, Signature={signature}'
    return out


class R2:
    """The few S3 calls the job needs on one R2 bucket: GET, HEAD and PUT with metadata."""

    def __init__(self, account, access_key, secret_key, bucket=BUCKET, opener=urlopen, clock=None):
        self.endpoint = f'https://{account}.r2.cloudflarestorage.com'
        self.access_key, self.secret_key, self.bucket = access_key, secret_key, bucket
        self.opener = opener
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_token(cls, token, account, **kwargs):
        # Cloudflare documents S3 credentials for an API token: key id = token id, secret = sha256(token).
        return cls(account, token_id(token, account), hashlib.sha256(token.encode()).hexdigest(), **kwargs)

    def _call(self, method, key, body=b'', headers=None):
        url = f'{self.endpoint}/{self.bucket}/{_uri(key)}'
        payload = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA
        sent = sign_v4(method, url, {**(headers or {}), 'x-amz-content-sha256': payload}, payload,
                       self.access_key, self.secret_key, self.clock())
        request = Request(url, data=body if method == 'PUT' else None, method=method, headers=sent)
        try:
            with self.opener(request, timeout=60) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except HTTPError as error:
            if error.code == 404:
                return 404, {}, b''
            raise Transient(f'R2 {method} HTTP {error.code}') from None
        except OSError as error:
            raise Transient(f'R2 {method} {type(error).__name__}') from None

    def get(self, key):
        status, _, body = self._call('GET', key)
        return None if status == 404 else body

    def head(self, key):
        """The object's x-amz-meta-* values (prefix removed), or None when it does not exist."""
        status, headers, _ = self._call('HEAD', key)
        if status == 404:
            return None
        return {k[len('x-amz-meta-'):]: v for k, v in headers.items() if k.startswith('x-amz-meta-')}

    def put(self, key, body, metadata, content_type='image/jpeg'):
        headers = {'content-type': content_type, **{f'x-amz-meta-{k}': str(v) for k, v in metadata.items()}}
        self._call('PUT', key, body, headers)

    def get_file(self, key, path):
        """Stream the object to `path` (a video can be 300 MB); False when it does not exist."""
        url = f'{self.endpoint}/{self.bucket}/{_uri(key)}'
        sent = sign_v4('GET', url, {'x-amz-content-sha256': EMPTY_SHA}, EMPTY_SHA, self.access_key, self.secret_key, self.clock())
        try:
            with self.opener(Request(url, method='GET', headers=sent), timeout=60) as response, open(path, 'wb') as out:
                shutil.copyfileobj(response, out, 1 << 20)
            return True
        except HTTPError as error:
            if error.code == 404:
                return False
            raise Transient(f'R2 GET HTTP {error.code}') from None
        except OSError as error:
            raise Transient(f'R2 GET {type(error).__name__}') from None

    def put_file(self, key, path, metadata, content_type='video/mp4'):
        self.put(key, Path(path).read_bytes(), metadata, content_type)


# ---- the Worker's job API -----------------------------------------------------------

class Api:
    """GET the work list and POST each result, with a fresh OIDC token every few minutes."""

    def __init__(self, base, audience, opener=urlopen, token_source=None, clock=time.monotonic):
        self.base, self.audience, self.opener, self.clock = base.rstrip('/'), audience, opener, clock
        self.token_source = token_source or self._github_token
        self.user_agent = f'SkipperCast-advisor-media/0.1 (+{self.base})'
        self._token, self._at = None, -1e9

    def _github_token(self):
        url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'] + '&' + urlencode({'audience': self.audience})
        request = Request(url, headers={'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN'],
                                        'User-Agent': self.user_agent})
        with self.opener(request, timeout=20) as response:
            return json.load(response)['value']

    def token(self):
        # GitHub's tokens live about five minutes; the Worker refuses any lifetime over ten.
        if self._token is None or self.clock() - self._at > 240:
            self._token, self._at = self.token_source(), self.clock()
        return self._token

    def _call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {'Authorization': 'Bearer ' + self.token(), 'User-Agent': self.user_agent, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.base + path, data=data, headers=headers, method='POST' if data is not None else 'GET')
        try:
            with self.opener(request, timeout=55) as response:
                return json.load(response)
        except HTTPError as error:
            raise Transient(f'{path} HTTP {error.code}') from None
        except OSError as error:
            raise Transient(f'{path} {type(error).__name__}') from None

    def pending(self):
        return self._call('/api/advisor/jobs/media')

    def done(self, payload):
        return self._call('/api/advisor/jobs/media-done', payload)


# ---- drawing (Pillow) -----------------------------------------------------------------

def load_spec(path=GRAPHICS):
    return json.loads(Path(path).read_text())


def _pil():
    from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps
    return Image, ImageCms, ImageDraw, ImageFont, ImageOps


def font(spec, size):
    _, _, _, ImageFont, _ = _pil()
    face = spec['fonts'].get('ttf')
    if face:
        return ImageFont.truetype(str(ROOT / face), size)
    return ImageFont.load_default(size=size)


def orientation_transpose(orientation):
    """The Pillow transpose that makes an image stored with this EXIF orientation upright; None for 1 or anything unknown.

    The same table as ImageOps.exif_transpose, which cannot be used on a stored
    JPEG: the Worker stripped its EXIF and passes the value separately.
    """
    T = _pil()[0].Transpose
    return {2: T.FLIP_LEFT_RIGHT, 3: T.ROTATE_180, 4: T.FLIP_TOP_BOTTOM, 5: T.TRANSPOSE,
            6: T.ROTATE_270, 7: T.TRANSVERSE, 8: T.ROTATE_90}.get(orientation)


def upright(image, orientation):
    """The image turned upright by a stored EXIF orientation (1-8); unchanged for 1, None or anything else."""
    method = orientation_transpose(orientation) if isinstance(orientation, int) and not isinstance(orientation, bool) else None
    return image.transpose(method) if method is not None else image


def decode(data, mime, orientation=None):
    """An RGB image in sRGB, upright, from the original's bytes; Unreadable when Pillow cannot decode it.

    `orientation` is the EXIF value the Worker read before stripping a JPEG
    (the work list's `orientation`); when it is None the file's own EXIF, if
    any (HEIC and other originals stored as received), is applied instead.
    """
    Image, ImageCms, _, _, ImageOps = _pil()
    if mime in HEIF:
        try:
            import pillow_heif
        except ImportError:
            raise Unreadable('heic-unsupported: pillow-heif is not installed') from None
        pillow_heif.register_heif_opener()
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError) as error:
        raise Unreadable(f'decode-failed: {type(error).__name__}') from None
    icc = image.info.get('icc_profile')
    image = ImageOps.exif_transpose(image) if orientation is None else upright(image, orientation)
    if image.mode in ('RGBA', 'LA', 'P', 'PA'):
        image = image.convert('RGBA')
        flat = Image.new('RGB', image.size, (255, 255, 255))
        flat.paste(image, mask=image.getchannel('A'))
        image = flat
    elif image.mode != 'RGB':
        image = image.convert('RGB')
    if icc:
        try:
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                              ImageCms.createProfile('sRGB'), outputMode='RGB')
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass  # an unusable profile: keep the pixels as they are
    return image


def fit(image, max_side):
    """A copy no larger than max_side on its long side (never enlarged)."""
    Image = _pil()[0]
    copy = image.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return copy


def cover(image, box_size):
    """The image scaled to cover box_size and centre-cropped to it."""
    Image, _, _, _, ImageOps = _pil()
    return ImageOps.fit(image, box_size, Image.Resampling.LANCZOS)


def contain(image, box_size):
    """The image scaled to fit inside box_size (enlarged if smaller), aspect kept."""
    Image = _pil()[0]
    w, h = image.size
    scale = min(box_size[0] / w, box_size[1] / h)
    return image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)


def jpeg(image, quality):
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=quality, optimize=True, progressive=True)   # no exif=, no icc_profile=: plain sRGB
    return buffer.getvalue()


def display_number(number):
    """+18055550100 -> (805) 555-0100; anything else as given; None for empty."""
    digits = ''.join(c for c in (number or '') if c.isdigit())
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) == 10:
        return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'
    return (number or '').strip() or None


def wrap(draw, text, face, width):
    words, lines, line = str(text).split(), [], ''
    for word in words:
        candidate = f'{line} {word}'.strip()
        if line and draw.textlength(candidate, font=face) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def text_block(draw, box, text, face, fill, spacing=1.25, max_lines=None):
    """Draw wrapped text from the box's top-left; returns the y below it."""
    left, top, right, bottom = box
    size = getattr(face, 'size', 20)
    y = top
    for i, line in enumerate(wrap(draw, text, face, right - left)):
        if (max_lines and i >= max_lines) or y + size > bottom:
            break
        draw.text((left, y), line, font=face, fill=tuple(fill))
        y += round(size * spacing)
    return y


def band(draw, spec, box, number):
    """The footer band: brand colour, "Text SkipperCast" and the number (or the fallback) centred."""
    colors, fonts = spec['colors'], spec['fonts']
    draw.rectangle(box, fill=tuple(colors['band']))
    left, top, right, bottom = box
    title, sub = spec['footer']['text'], display_number(number) or spec['footer']['fallback']
    big, small = font(spec, fonts['footer']), font(spec, fonts['footer_number'])
    total = fonts['footer'] + 18 + fonts['footer_number']
    y = top + (bottom - top - total) // 2
    for text, face, size in ((title, big, fonts['footer']), (sub, small, fonts['footer_number'])):
        width = draw.textlength(text, font=face)
        draw.text((left + (right - left - width) / 2, y), text, font=face, fill=tuple(colors['band_text']))
        y += size + 18


def canvas(spec, size):
    Image, _, ImageDraw, _, _ = _pil()
    image = Image.new('RGB', tuple(size), tuple(spec['colors']['field']))
    return image, ImageDraw.Draw(image)


def place(image, photo, box, mode='contain'):
    left, top, right, bottom = box
    size = (right - left, bottom - top)
    fitted = cover(photo, size) if mode == 'cover' else contain(photo, size)
    image.paste(fitted, (left + (size[0] - fitted.width) // 2, top + (size[1] - fitted.height) // 2))


def story_image(spec, photo, number, title=None, lines=()):
    """1080 x 1920: the photo centred on the dark field, the footer band at the bottom."""
    layout = spec['story']
    image, draw = canvas(spec, layout['size'])
    if photo is not None:
        place(image, photo, layout['photo_box'])
    if title:
        text_block(draw, layout['title_box'], title, font(spec, spec['fonts']['title']), spec['colors']['text'], max_lines=3)
    y = layout['lines_box'][1]
    for line in lines:
        box = [layout['lines_box'][0], y, layout['lines_box'][2], layout['lines_box'][3]]
        y = text_block(draw, box, line, font(spec, spec['fonts']['body']), spec['colors']['text']) + 12
    band(draw, spec, layout['band_box'], number)
    return image


def line_text(item):
    if isinstance(item, dict):
        label, value = item.get('label', ''), item.get('value', '')
        return f'{label}: {value}' if label and value != '' else str(label or value)
    return str(item)


def card(spec, layout, number, title, lines, note=None):
    """A text card (daily post, roundup cover): title, one line per item, a note, the band."""
    colors, fonts = spec['colors'], spec['fonts']
    image, draw = canvas(spec, layout['size'])
    text_block(draw, layout['title_box'], title, font(spec, fonts['title']), colors['accent'], max_lines=2)
    left, top, right, bottom = layout['lines_box']
    y, face = top, font(spec, fonts['body'])
    for item in lines:
        if y + fonts['body'] > bottom:
            break
        y = text_block(draw, [left, y, right, bottom], line_text(item), face, colors['text'], max_lines=2) + 16
    if note and 'note_box' in layout:
        text_block(draw, layout['note_box'], note, font(spec, fonts['small']), colors['muted'], max_lines=3)
    band(draw, spec, layout['band_box'], number)
    return image


def daily_graphic(spec, data, number):
    """The daily "what's biting" card from data: title or port and date, lines [{label, value}], conditions, confidence."""
    title = data.get('title') or ' '.join(str(p) for p in (data.get('port'), data.get('date')) if p) or "What's biting"
    note = ' · '.join(str(p) for p in (data.get('conditions'), data.get('confidence')) if p) or None
    return card(spec, spec['daily'], number, title, data.get('lines') or [], note)


def roundup_slides(spec, data, photos, number):
    """The cover card, then one slide per photo with its caption (data.captions[i])."""
    layout = spec['roundup']
    slides = [card(spec, layout, number, data.get('title') or 'This week', data.get('lines') or [])]
    captions = data.get('captions') or []
    for i, photo in enumerate(photos[:layout['max_slides'] - 1]):
        image, draw = canvas(spec, layout['size'])
        place(image, photo, layout['photo_box'], mode='cover')
        if i < len(captions) and captions[i]:
            text_block(draw, layout['caption_box'], captions[i], font(spec, spec['fonts']['small']), spec['colors']['text'], max_lines=2)
        band(draw, spec, layout['band_box'], number)
        slides.append(image)
    return slides



# ---- video: container metadata out (00 principle 7) ------------------------------------

STRIPPED = '1'                         # x-amz-meta-stripped: the version of the strip below
# Boxes whose payload is a list of boxes (ISO-BMFF / QuickTime); `meta` may be a full box.
_CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'dinf', b'edts', b'udta', b'meta', b'ilst', b'moof', b'traf', b'mvex'}
_LOCATION_BOXES = {b'\xa9xyz': 'xyz-atom', b'loci': 'loci-atom'}
_LOCATION_WORDS = (b'com.apple.quicktime.location', b'iso6709')


def _boxes(data, start, end):
    """(type, payload start, box end) of each box between start and end; stops at anything malformed."""
    at = start
    while at + 8 <= end:
        size = int.from_bytes(data[at:at + 4], 'big')
        kind = bytes(data[at + 4:at + 8])
        head = 8
        if size == 1:
            if at + 16 > end:
                return
            size, head = int.from_bytes(data[at + 8:at + 16], 'big'), 16
        elif size == 0:
            size = end - at
        if size < head or at + size > end:
            return
        yield kind, at + head, at + size
        at += size


def location_atoms(data):
    """The location metadata the boxes of an MP4/MOV (its bytes, or one top-level box) still carry.

    Finds a udta ©xyz atom, a 3GPP loci atom and a QuickTime keys entry (or any
    other leaf box) naming com.apple.quicktime.location.* or ISO 6709; returns
    their names, sorted and unique, so [] means clean. mdat (the samples) is not
    read. Pure: works on bytes, never raises.
    """
    found = set()

    def walk(start, end, depth):
        for kind, body, stop in _boxes(data, start, end):
            if kind in _LOCATION_BOXES:
                found.add(_LOCATION_BOXES[kind])
            if kind == b'mdat':
                continue
            if kind in _CONTAINERS and depth < 12:
                # A full-box `meta` (ISO) starts with version and flags; a QuickTime one does not.
                inner = body + 4 if kind == b'meta' and data[body:body + 4] == b'\0\0\0\0' else body
                walk(inner, stop, depth + 1)
            elif any(word in bytes(data[body:stop]).lower() for word in _LOCATION_WORDS):
                found.add(kind.decode('latin-1').strip(' \0').encode('ascii', 'replace').decode() + '-location')

    walk(0, len(data), 0)
    return sorted(found)


def file_location_atoms(path):
    """location_atoms over a file, one top-level box at a time; mdat (the samples) is skipped, never read."""
    found = set()
    size = os.path.getsize(path)
    with open(path, 'rb') as handle:
        at = 0
        while at + 8 <= size:
            handle.seek(at)
            head = handle.read(16)
            box, kind, length = int.from_bytes(head[:4], 'big'), head[4:8], 8
            if box == 1:
                box, length = int.from_bytes(head[8:16], 'big'), 16
            elif box == 0:
                box = size - at
            if box < length or at + box > size:
                found.add('malformed')
                break
            if kind in _LOCATION_BOXES:
                found.add(_LOCATION_BOXES[kind])
            if kind != b'mdat':
                handle.seek(at)
                found.update(location_atoms(handle.read(box)))
            at += box
    return sorted(found)


def location_tags(probe_json):
    """ffprobe -show_format -show_streams JSON: every tag whose name says location (format or stream), as 'where:name'."""
    out = []
    probe_json = probe_json or {}
    sections = [('format', probe_json.get('format') or {})] + [(f'stream{i}', s) for i, s in enumerate(probe_json.get('streams') or [])]
    for where, section in sections:
        for name in section.get('tags') or {}:
            low = name.lower()
            if 'location' in low or 'xyz' in low or 'iso6709' in low or 'gps' in low:
                out.append(f'{where}:{name}')
    return out


def strip_command(ffmpeg, source, out, hevc=False):
    """The stream copy without metadata: global, stream and chapter metadata dropped, data and subtitle tracks
    (a QuickTime timed-metadata track can hold location) left out, no encoder tags, moov first for streaming."""
    return [ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(source),
            '-map_metadata', '-1', '-map_metadata:s', '-1', '-map_chapters', '-1', '-dn', '-sn',
            '-c', 'copy', *(['-tag:v', 'hvc1'] if hevc else []),
            '-fflags', '+bitexact', '-flags:v', '+bitexact', '-flags:a', '+bitexact',
            '-movflags', '+faststart', '-f', 'mp4', str(out)]


def probe(ffprobe, path, run=None):
    """ffprobe's format and streams as JSON; Unreadable('probe-failed') when it cannot read the file."""
    result = (run or subprocess.run)([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                 capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise Unreadable('probe-failed')
    try:
        return json.loads(result.stdout or b'{}')
    except ValueError:
        raise Unreadable('probe-failed') from None


def derive_video(item, r2, log=print, which=None, run=None):
    """Strip one video to keys.video and return the media-done payload; Unreadable('no-ffmpeg') without ffmpeg."""
    key, sha = item['keys']['video'], item['sha256']
    meta = r2.head(key)
    if meta is not None and meta.get(META) == sha and meta.get('stripped') == STRIPPED:
        log(f'video {item["id"]}: unchanged, skipped')
        dims = _dims(meta)
        return {'media_id': item['id'], 'keys': {'video': key}, **({'width': dims[0], 'height': dims[1]} if dims else {})}
    which, run = which or shutil.which, run or subprocess.run
    ffmpeg, ffprobe = which('ffmpeg'), which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise Unreadable('no-ffmpeg')
    with tempfile.TemporaryDirectory(prefix='advisor-video-') as tmp:
        source, out = Path(tmp) / 'original', Path(tmp) / 'video.mp4'
        if not r2.get_file(item['r2_key'], source):
            raise Unreadable('original-missing')
        streams = [s for s in probe(ffprobe, source, run).get('streams') or []
                   if s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic')]
        if not streams:
            raise Unreadable('no-video-stream')
        try:
            done = run(strip_command(ffmpeg, source, out, streams[0].get('codec_name') == 'hevc'), capture_output=True, timeout=900, check=False)
        except subprocess.TimeoutExpired:
            raise Unreadable('ffmpeg-timeout') from None
        if done.returncode or not out.exists():
            raise Unreadable('ffmpeg-failed')
        result = probe(ffprobe, out, run)
        left = location_tags(result) + file_location_atoms(out)
        if left:
            raise Unreadable('location-left: ' + ', '.join(left)[:150])
        video = next((s for s in result.get('streams') or [] if s.get('codec_type') == 'video'), {})
        width, height = video.get('width'), video.get('height')
        dims = {'width': width, 'height': height} if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0 else {}
        r2.put_file(key, out, {META: sha, 'stripped': STRIPPED, **dims}, content_type='video/mp4')
        log(f'video {item["id"]}: {item["bytes"]} bytes -> {out.stat().st_size} bytes, metadata removed')
    return {'media_id': item['id'], 'keys': {'video': key}, **dims}

# ---- the job -----------------------------------------------------------------------

def _dims(meta):
    try:
        return int(meta['width']), int(meta['height'])
    except (KeyError, TypeError, ValueError):
        return None


def derive_media(item, r2, spec, number, log=print):
    """Write public, thumb and story for one media item; returns the media-done payload."""
    keys, sha = item['keys'], item['sha256']
    orientation = item.get('orientation')
    turned = str(orientation) if type(orientation) is int and 1 <= orientation <= 8 else '1'
    metas = {name: r2.head(key) for name, key in keys.items()}
    # Files made before orientation was recorded carry no value: they count as '1'.
    if all(m is not None and m.get(META) == sha and m.get('orientation', '1') == turned for m in metas.values()) and _dims(metas['public']):
        width, height = _dims(metas['public'])
        source = _dims({'width': metas['public'].get('source-width'), 'height': metas['public'].get('source-height')})
        log(f'media {item["id"]}: unchanged, skipped')
        return {'media_id': item['id'], 'keys': keys, 'width': width, 'height': height,
                **({'source_width': source[0], 'source_height': source[1]} if source else {})}
    original = r2.get(item['r2_key'])
    if original is None:
        raise Unreadable('original-missing')
    photo = decode(original, item['mime'], orientation)
    public = fit(photo, spec['public']['max_side'])
    thumb = fit(photo, spec['thumb']['max_side'])
    story = story_image(spec, public, number)
    common = {META: sha, 'orientation': turned, 'source-width': photo.width, 'source-height': photo.height}
    # public.jpg last: its metadata is what a rerun checks first for the sizes.
    r2.put(keys['thumb'], jpeg(thumb, spec['thumb']['quality']), {**common, 'width': thumb.width, 'height': thumb.height})
    r2.put(keys['story'], jpeg(story, spec['story']['quality']), {**common, 'width': story.width, 'height': story.height})
    r2.put(keys['public'], jpeg(public, spec['public']['quality']), {**common, 'width': public.width, 'height': public.height})
    log(f'media {item["id"]}: {photo.width}x{photo.height} (orientation {turned}) -> {public.width}x{public.height}')
    return {'media_id': item['id'], 'keys': keys, 'width': public.width, 'height': public.height,
            'source_width': photo.width, 'source_height': photo.height}


def request_digest(item):
    """What a graphic is rendered from: kind, data and its photos' sources."""
    basis = {'kind': item['kind'], 'data': item.get('data') or {}, 'media': [m['id'] for m in item.get('media') or []]}
    return hashlib.sha256(json.dumps(basis, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _photo(r2, spec, source):
    """A graphic's photo: the media's public.jpg when it exists, else its original, reduced the same way."""
    data = r2.get(source['public_key'])
    if data is not None:
        return decode(data, 'image/jpeg')
    data = r2.get(source['r2_key'])
    if data is None:
        raise Unreadable('original-missing')
    return fit(decode(data, source['mime'], source.get('orientation')), spec['public']['max_side'])


def render_graphic(item, r2, spec, number, log=print):
    """Render one graphic request to its out_key (roundup slides beside it); returns the media-done payload."""
    digest, out = request_digest(item), item['out_key']
    stem = out[:-len('.jpg')]
    meta = r2.head(out)
    if meta is not None and meta.get(META) == digest and _dims(meta):
        width, height = _dims(meta)
        slides = [f'{stem}-{i}.jpg' for i in range(1, int(meta.get('slides', '0') or 0) + 1)]
        log(f'graphic {item["id"]}: unchanged, skipped')
        return {'graphic_id': item['id'], 'keys': {'public': out, **({'slides': slides} if slides else {})}, 'width': width, 'height': height}
    photos = [_photo(r2, spec, source) for source in item.get('media') or []]
    data = item.get('data') or {}
    kind = item['kind']
    if kind == 'daily':
        images = [daily_graphic(spec, data, number)]
    elif kind == 'story':
        lines = [line_text(x) for x in data.get('lines') or []]
        images = [story_image(spec, photos[0] if photos else None, number, data.get('title'), lines)]
    elif kind == 'roundup':
        images = roundup_slides(spec, data, photos, number)
    else:
        raise Unreadable(f'unknown-kind: {kind}')
    quality = spec.get(kind, spec['daily']).get('quality', 88)
    slides = [f'{stem}-{i}.jpg' for i in range(1, len(images))]
    for key, image in zip(slides, images[1:]):
        r2.put(key, jpeg(image, quality), {META: digest, 'width': image.width, 'height': image.height})
    cover_image = images[0]
    r2.put(out, jpeg(cover_image, quality), {META: digest, 'width': cover_image.width, 'height': cover_image.height, 'slides': len(slides)})
    log(f'graphic {item["id"]}: {kind}, {len(images)} image(s)')
    return {'graphic_id': item['id'], 'keys': {'public': out, **({'slides': slides} if slides else {})},
            'width': cover_image.width, 'height': cover_image.height}


def run(api, r2, spec, number, max_rounds=20, log=print):
    """Process pending work until the list is empty (or only items already tried remain). Returns counts."""
    counts = {'media': 0, 'graphics': 0, 'videos': 0, 'failed': 0, 'transient': 0}
    tried = set()
    for _ in range(max_rounds):
        work = api.pending()
        todo = [('media', m) for m in work.get('media', []) if ('m', m['id']) not in tried]
        todo += [('graphic', g) for g in work.get('graphics', []) if ('g', g['id']) not in tried]
        todo += [('video', v) for v in work.get('videos', []) if ('v', v['id']) not in tried]
        if not todo:
            break
        for kind, item in todo:
            tried.add((kind[0], item['id']))
            ident = {'graphic_id': item['id']} if kind == 'graphic' else {'media_id': item['id']}
            try:
                if kind == 'media':
                    payload = derive_media(item, r2, spec, number, log)
                elif kind == 'video':
                    payload = derive_video(item, r2, log)
                else:
                    payload = render_graphic(item, r2, spec, number, log)
            except Unreadable as error:
                log(f'::warning title=Advisor media given up::{kind} {item["id"]}: {error}')
                payload, outcome = {**ident, 'error': str(error)[:200]}, 'failed'
            except Transient as error:
                log(f'::warning title=Advisor media retry later::{kind} {item["id"]}: {error}')
                counts['transient'] += 1
                continue
            else:
                outcome = {'media': 'media', 'video': 'videos'}.get(kind, 'graphics')
            try:
                api.done(payload)
            except Transient as error:
                log(f'::warning title=Advisor media report failed::{kind} {item["id"]}: {error}')
                counts['transient'] += 1
                continue
            counts[outcome] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--max-rounds', type=int, default=20)
    args = parser.parse_args(argv)
    token, account = os.environ.get('R2_ADVISOR_TOKEN'), os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not account:
        print('::error title=Advisor media not configured::R2_ADVISOR_TOKEN and CLOUDFLARE_ACCOUNT_ID are required')
        return 1
    deployment = json.loads(DEPLOYMENT.read_text())
    base = os.environ.get('ADVISOR_PUBLIC_BASE') or deployment['public_origin']
    api = Api(base, deployment['public_origin'] + '/api/advisor/jobs')
    try:
        counts = run(api, R2.from_token(token, account), load_spec(), os.environ.get('ADVISOR_NUMBER'), args.max_rounds)
    except Transient as error:
        print(f'::error title=Advisor media job failed::{error}')
        return 1
    print(json.dumps(counts))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as handle:
            handle.write('\n## Advisor media\n' + json.dumps(counts) + '\n')
    return 1 if counts['transient'] else 0


if __name__ == '__main__':
    sys.exit(main())
