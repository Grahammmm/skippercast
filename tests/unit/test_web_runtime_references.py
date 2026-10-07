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
