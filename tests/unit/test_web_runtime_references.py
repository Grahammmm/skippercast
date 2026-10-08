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
    "export const C = () => <div dangerouslySetInnerHTML={{__html: s}} />;\n",
    "const url = 'https://s.test/'; el.innerHTML = url;\n",
])
def test_check_web_fails_on_inner_html_outside_the_markup_host(tmp_path, source):
    write_web(tmp_path, "app/Other.tsx", source)
    found = checker.inner_html_assignments(tmp_path)
    assert len(found) == 1 and found[0].startswith("web/app/Other.tsx:"), found


def test_check_web_ignores_inner_html_in_comments_comparisons_and_the_host(tmp_path):
    write_web(tmp_path, "ui/icons.tsx", "// never sets el.innerHTML = s\n/* el.innerHTML = s\n */ const x = 1;\n")
    write_web(tmp_path, "a.ts", "if (el.innerHTML === '') {}\nconst url = 'https://s.test/'; // el.innerHTML = s\n")
    write_web(tmp_path, "app/CoastMarkup.tsx", "content.innerHTML = markup;\n")
    write_web(tmp_path, "notes.md", "el.innerHTML = s\n")
    assert checker.inner_html_assignments(tmp_path) == []


def test_check_web_inner_html_line_numbers_survive_block_comments(tmp_path):
    write_web(tmp_path, "b.ts", "/* one\ntwo */\nel.innerHTML = s;\n")
    assert checker.inner_html_assignments(tmp_path) == ["web/b.ts:3"]


def test_check_web_only_the_markup_host_assigns_inner_html_in_web():
    assert checker.inner_html_assignments() == []
    assert (ROOT / checker.MARKUP_HOST).is_file()
