import runpy

from tests._support import ROOT

markup_sinks = runpy.run_path(str(ROOT / "scripts/check_web.py"))["markup_sinks"]


def test_unlisted_markup_sink_in_coast_source_is_reported(tmp_path):
    # A web-only scan misses a new sink in the shared package, even in a nested file.
    source = tmp_path / "packages/coast/src/fixture/nested.ts"
    source.parent.mkdir(parents=True)
    source.write_text("// inert fixture\nshadow.innerHTML = '<p>fixture</p>';\n")

    assert markup_sinks(tmp_path) == ["packages/coast/src/fixture/nested.ts:2"]


def test_existing_coast_exception_does_not_exempt_the_whole_file(tmp_path):
    # A file-wide exception would also admit a new assignment in the legacy report.
    relative = "packages/coast/src/coast3d/report.ts"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    original = (ROOT / relative).read_text()
    source.write_text(original)
    assert markup_sinks(tmp_path) == []

    source.write_text(original + "\nshadow.innerHTML = '<p>fixture</p>';\n")
    assert markup_sinks(tmp_path) == [f"{relative}:{original.count(chr(10)) + 2}"]
