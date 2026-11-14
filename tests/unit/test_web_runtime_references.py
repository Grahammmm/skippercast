import importlib.util
import pytest

from tests._support import ROOT
spec = importlib.util.spec_from_file_location("web_reference_checker", ROOT / "scripts/check_web.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

def check(tmp_path, monkeypatch, html):
    monkeypatch.setattr(checker, "WEB", tmp_path)
    page = tmp_path / "page.html"
    page.write_text(html)
    checker.check_page_references(page)

@pytest.mark.parametrize("html", [
    '<script src="/report"></script>',
    '<link rel="stylesheet" href="/feed.xml">',
    '<img src="/methodology">',
    '<a href="/unknown-route">Missing</a>',
    '<link rel="alternate" type="application/rss+xml" href="/unknown-feed.xml">',
])
def test_runtime_route_names_cannot_hide_missing_static_resources(tmp_path, monkeypatch, html):
    with pytest.raises(AssertionError):
        check(tmp_path, monkeypatch, html)

def test_registered_navigation_and_exact_rss_links_are_valid(tmp_path, monkeypatch):
    (tmp_path / "privacy.html").write_text("Complete existing notice")
    check(tmp_path, monkeypatch, '<a href="/report">Report</a><a href="/methodology">Methods</a><a href="/about">About</a><a href="/privacy">Privacy</a><link rel="alternate" type="application/rss+xml" href="/feed.xml">')


def write_web(tmp_path, name, source):
    path = tmp_path / "web" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


@pytest.mark.parametrize("source", [
    "el.innerHTML = markup;\n",
    "const a = 1;\nnode . innerHTML += '<b>x</b>';\n",
    "node['innerHTML'] = s;\n",
    "el.outerHTML = s;\n",
    "el[\"outerHTML\"] = s;\n",
    "el.insertAdjacentHTML('beforeend', s);\n",
    "Object.assign(el, {innerHTML: s});\n",
    "Object.assign(el, {outerHTML: s});\n",
    "Object.assign(el, {'innerHTML': s});\n",
    "Reflect.set(el, 'innerHTML', s);\n",
    "Reflect.set(el, \"outerHTML\", s);\n",
    "Object.defineProperty(el, 'innerHTML', {value: s});\n",
    "el[`innerHTML`] = s;\n",
    "const key = `outerHTML`; el[key] = s;\n",
    "export const C = () => <div dangerouslySetInnerHTML={{__html: s}} />;\n",
    "document.write(s);\n",
    "document . writeln(s);\n",
    "el.setHTMLUnsafe(s);\n",
    "document.createRange().createContextualFragment(s);\n",
    "new DOMParser().parseFromString(s, 'text/html');\n",
    "const url = 'https://s.test/'; el.innerHTML = url;\n",
    "const re = /https?:\\/\\//; el.innerHTML = s;\n",
    "const re = /[//]/g; el.innerHTML = s;\n",
    "if (ok) return /\\/\\//.test(x) && (el.innerHTML = s);\n",
])
def test_check_web_fails_on_markup_sinks_outside_the_markup_host(tmp_path, source):
    write_web(tmp_path, "app/Other.tsx", source)
    found = checker.markup_sinks(tmp_path)
    assert len(found) == 1 and found[0].startswith("web/app/Other.tsx:"), found


def test_check_web_ignores_markup_sinks_in_comments_comparisons_and_the_host(tmp_path):
    write_web(tmp_path, "ui/icons.tsx", "// never sets el.innerHTML = s\n/* el.outerHTML = s\n */ const x = 1;\n")
    write_web(tmp_path, "a.ts", "if (el.innerHTML === '') {}\nconst url = 'https://s.test/'; // el.innerHTML = s\n")
    write_web(tmp_path, "b.ts", "const half = total / 2; // document.write(s)\nconst re = /a/g; // el.insertAdjacentHTML(s)\n")
    write_web(tmp_path, "app/CoastMarkup.tsx", "content.innerHTML = markup;\n")
    write_web(tmp_path, "notes.md", "el.innerHTML = s\n")
    assert checker.markup_sinks(tmp_path) == []


def test_check_web_markup_sink_line_numbers_survive_block_comments(tmp_path):
    write_web(tmp_path, "b.ts", "/* one\ntwo */\nel.innerHTML = s;\n")
    assert checker.markup_sinks(tmp_path) == ["web/b.ts:3"]


def test_check_web_only_the_markup_host_writes_markup_in_web():
    assert checker.markup_sinks() == []
    assert (ROOT / checker.MARKUP_HOST).is_file()


# SC2207-03: /skill is registered navigation to the existing forecast skill page.
def test_skill_anchor_passes_with_registration_and_page(tmp_path, monkeypatch):
    (tmp_path / "skill.html").write_text("Forecast skill")
    check(tmp_path, monkeypatch, '<a href="/skill">Skill</a><a href="/skill?ui=v1#rows">Skill</a>')


def test_skill_anchor_fails_without_the_page(tmp_path, monkeypatch):
    with pytest.raises(AssertionError):
        check(tmp_path, monkeypatch, '<a href="/skill">Skill</a>')


def test_skill_anchor_fails_without_the_route_registration(tmp_path, monkeypatch):
    (tmp_path / "skill.html").write_text("Forecast skill")
    routes = tmp_path / "root" / "server" / "routes"
    routes.mkdir(parents=True)
    (routes / "assets.ts").write_text("if(path === '/status') return '/status.html';\n")
    monkeypatch.setattr(checker, "ROOT", tmp_path / "root")
    with pytest.raises(AssertionError):
        check(tmp_path, monkeypatch, '<a href="/skill">Skill</a>')


@pytest.mark.parametrize("html", [
    '<script src="/skill"></script>',
    '<link rel="stylesheet" href="/skill">',
    '<img src="/skill">',
    '<a href="/skill/">Trailing slash</a>',
    '<a href="/skillx">Other</a>',
    '<a href="/Skill">Case</a>',
    '<a href="/skill/child">Child</a>',
])
def test_skill_route_is_navigation_only_and_exact(tmp_path, monkeypatch, html):
    (tmp_path / "skill.html").write_text("Forecast skill")
    with pytest.raises(AssertionError):
        check(tmp_path, monkeypatch, html)


# RF1020-4: SRI uses the strongest supported algorithm, as browsers do.
import base64
import hashlib
import socket

FIXTURE = b"synthetic vendor bytes\n"


def sri(algorithm, data=FIXTURE):
    return algorithm + "-" + base64.b64encode(hashlib.new(algorithm, data).digest()).decode()


def bad(algorithm):
    return sri(algorithm, b"different bytes")


ALGORITHMS = ["sha256", "sha384", "sha512"]
PAIRS = [("sha256", "sha384"), ("sha256", "sha512"), ("sha384", "sha512")]


@pytest.mark.parametrize("weak,strong", PAIRS)
@pytest.mark.parametrize("weak_first", [True, False])
def test_sri_stronger_mismatch_is_not_rescued(weak, strong, weak_first):
    tokens = [sri(weak), bad(strong)]
    tokens = tokens if weak_first else tokens[::-1]
    assert checker.sri_digest(" ".join(tokens), FIXTURE) is False


def test_sri_stronger_mismatch_is_not_rescued_by_any_lower_algorithm():
    assert checker.sri_digest(" ".join([sri("sha256"), sri("sha384"), bad("sha512")]), FIXTURE) is False
    assert checker.sri_digest(" ".join([bad("sha512"), sri("sha384"), sri("sha256")]), FIXTURE) is False


def test_sri_strongest_match_and_equal_strength_alternatives():
    for algorithm in ALGORITHMS:
        assert checker.sri_digest(sri(algorithm), FIXTURE) is True
    for weak, strong in PAIRS:
        assert checker.sri_digest(bad(weak) + " " + sri(strong), FIXTURE) is True
        assert checker.sri_digest(sri(strong) + " " + bad(weak), FIXTURE) is True
    for algorithm in ALGORITHMS:
        other = bad(algorithm)
        good = sri(algorithm)
        assert checker.sri_digest(f"{other} {good}", FIXTURE) is True
        assert checker.sri_digest(f"{good} {other}", FIXTURE) is True
        assert checker.sri_digest(f"{good} {good} {other}", FIXTURE) is True
        assert checker.sri_digest(f"{other} {other}", FIXTURE) is False


@pytest.mark.parametrize("integrity,expected", [
    ("", False),
    (" \t\n ", False),
    ("md5-abc sha1-abc sha999-abc", False),
    ("nohyphen", False),
    (bad("sha256"), False),
    ("md5-abc " + sri("sha256"), True),
    ("sha1-abc\t" + sri("sha384"), True),
    (bad("sha384") + " " + sri("sha256"), False),
    ("sha384- " + sri("sha256"), True),
    ("sha512-\n" + sri("sha384"), True),
    (sri("sha256") + "\n" + sri("sha384") + "\t" + bad("sha512"), False),
    (sri("sha256") + "\t\n" + sri("sha256"), True),
])
def test_sri_empty_unknown_and_nonmatching_tokens(integrity, expected):
    assert checker.sri_digest(integrity, FIXTURE) is expected


@pytest.fixture
def vendor_site(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access in a unit test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    web = tmp_path / "dist"
    (web / "vendor").mkdir(parents=True)
    (web / "vendor" / "fixture.js").write_bytes(FIXTURE)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "WEB", web)
    pinned = {"dist/vendor/fixture.js": hashlib.sha256(FIXTURE).hexdigest()}

    def page(tag_html):
        (web / "page.html").write_text("<!doctype html><html><body>" + tag_html + "</body></html>")
    return page, pinned


def tags(integrity):
    attr = f' integrity="{integrity}"' if integrity else ""
    return {
        "script": f'<script src="vendor/fixture.js"{attr}></script>',
        "stylesheet": f'<link rel="stylesheet" href="vendor/fixture.js"{attr}>',
    }


@pytest.mark.parametrize("kind", ["script", "stylesheet"])
@pytest.mark.parametrize("integrity", [
    sri("sha256") + " " + bad("sha384"),
    bad("sha512") + " " + sri("sha256"),
    sri("sha384") + " " + bad("sha512"),
    sri("sha256") + " " + sri("sha384") + " " + bad("sha512"),
])
def test_vendor_integrity_refuses_stronger_mismatch(vendor_site, kind, integrity):
    page, pinned = vendor_site
    page(tags(integrity)[kind])
    with pytest.raises(AssertionError) as raised:
        checker.check_vendor_integrity(pinned)
    path, ref, message = raised.value.args[0]
    assert path.name == "page.html" and ref == "vendor/fixture.js"
    assert message == "integrity does not match the file"


@pytest.mark.parametrize("kind", ["script", "stylesheet"])
@pytest.mark.parametrize("integrity", [
    sri("sha512"),
    bad("sha512") + " " + sri("sha512") + " " + bad("sha256"),
    bad("sha256") + " " + sri("sha384"),
    sri("sha256") + " " + sri("sha256"),
])
def test_vendor_integrity_accepts_matching_strongest_alternative(vendor_site, kind, integrity):
    page, pinned = vendor_site
    page(tags(integrity)[kind])
    checker.check_vendor_integrity(pinned)


@pytest.mark.parametrize("kind", ["script", "stylesheet"])
def test_vendor_integrity_still_needs_integrity_and_manifest_entry(vendor_site, kind):
    page, pinned = vendor_site
    page(tags("")[kind])
    with pytest.raises(AssertionError, match="vendor asset needs an integrity attribute"):
        checker.check_vendor_integrity(pinned)
    page(tags(sri("sha256"))[kind])
    with pytest.raises(AssertionError, match="missing from scripts/web-vendor-sha256.json"):
        checker.check_vendor_integrity({})
