"""docs/region-pipeline.md lists the mapping chain as one runnable command per stage, in the runner's order."""
import re
import shlex

import pytest

from scripts.relief import region as REGION
from scripts.relief import run_region as RR
from skippercast.relief import receipts
from tests._support import ROOT

DOC = ROOT / 'docs' / 'region-pipeline.md'
BEGIN, END = '<!-- mapping-chain-stages:begin -->', '<!-- mapping-chain-stages:end -->'
SECTION = re.compile(r'^## Mapping chain: one command per stage$(.*?)^## ', re.M | re.S)
LINK = re.compile(r'\]\(([^)#]+)(?:#[^)]*)?\)')
RUNNER = re.compile(r'^python (scripts/relief/run_region\.py .*)$', re.M)
CHAIN_LINE = re.compile(r'^\s*\d+\. .*?/region\.py (\S+) --region (\S+) --out (\S+)(.*)$', re.M)
REGION_ID = 'morro-bay'  # a real region with a render recipe, so the preview resolves its style


def _section():
    match = SECTION.search(DOC.read_text(encoding='utf-8'))
    assert match, 'region-pipeline.md has no "Mapping chain: one command per stage" section'
    return match.group(1)


def _stage_rows(section):
    table = section.split(BEGIN, 1)[1].split(END, 1)[0]
    return [line for line in table.splitlines() if line.startswith('| `')]


def _documented_options():
    """``{stage: options text}`` from the table's options column ('' for none)."""
    options = {}
    for row in _stage_rows(_section()):
        cells = [cell.strip() for cell in row.strip('|').split('|')]
        assert len(cells) == 4, row
        options[cells[0].strip('`')] = '' if cells[2] == 'none' else cells[2].strip('`')
    return options


@pytest.fixture
def host(tmp_path):
    """Placeholder values of the documented command, as real local paths."""
    out, norm = tmp_path / 'out', tmp_path / 'norm'
    out.mkdir()
    norm.mkdir()
    basemap = tmp_path / 'basemap.pmtiles'
    basemap.write_bytes(b'fixture')
    return {'<id>': REGION_ID, '<OUT>': str(out), '<NORM>': str(norm), '<PMTILES>': str(basemap)}


def _fill(text, values):
    for name, value in values.items():
        text = text.replace(name, value)
    return text


def test_stage_table_lists_the_runner_chain_in_order():
    stages = [row.split('`')[1] for row in _stage_rows(_section())]
    assert stages == list(RR.STAGES)


def test_every_listed_stage_is_a_region_cli_stage_module():
    for stage in RR.STAGES:
        assert (ROOT / 'src' / 'skippercast' / 'relief' / f'{stage}.py').is_file(), stage


def test_every_link_in_the_section_resolves():
    section = _section()
    links = LINK.findall(section)
    assert len(links) >= len(RR.STAGES)
    missing = [link for link in links if not (DOC.parent / link).resolve().is_file()]
    assert missing == []


def test_commands_in_the_section_name_existing_scripts():
    scripts = set(re.findall(r'python ((?:scripts)/[\w/]+\.py)', _section()))
    assert {'scripts/relief/region.py', 'scripts/relief/run_region.py'} <= scripts
    assert [path for path in sorted(scripts) if not (ROOT / path).is_file()] == []


def test_documented_runner_preview_prints_each_documented_stage_command(host, tmp_path, capsys):
    """The doc's run_region command runs as written; its preview passes each stage the row's options."""
    commands = RUNNER.findall(_section())
    assert len(commands) == 1, commands
    argv = shlex.split(_fill(commands[0], host))[1:]
    cfg = RR.Config(slot_dir=tmp_path / 'slots', stop_files=())
    assert RR.main(argv, cfg) == 0
    printed = {stage: (region, out, rest.strip()) for stage, region, out, rest in CHAIN_LINE.findall(capsys.readouterr().out)
               if stage != 'status'}
    assert list(printed) == list(RR.STAGES)
    documented = {stage: _fill(options, host) for stage, options in _documented_options().items()}
    assert printed == {stage: (REGION_ID, host['<OUT>'], documented[stage]) for stage in RR.STAGES}


class Parsed(Exception):
    """Raised where a stage, its arguments accepted, would open the region's output."""


# Values a real run binds from earlier receipts (see the section's last paragraph).
BOUND = {'<generation>': 'a' * 64, '<release-sha256>': 'b' * 64, '<shots-generation>': 'c' * 64,
         '<coarse family>': 'fixture-family'}


@pytest.fixture
def stage_cli(host, tmp_path, monkeypatch):
    """Run ``region.py <stage> ...`` up to the point where it would open the region."""
    def opened(*args, **kwargs):
        raise Parsed()

    monkeypatch.setattr(receipts, 'Region', opened)
    values = {**BOUND, '<coarse output>': str(tmp_path / 'coarse.tif'), '<water output>': str(tmp_path / 'water.geojson'),
              **host}

    def run(stage, options):
        argv = [stage, '--region', REGION_ID, '--out', host['<OUT>'], *shlex.split(_fill(options, values))]
        with pytest.raises((Parsed, SystemExit)) as exc:
            REGION.main(argv)
        return exc.value

    return run


@pytest.mark.parametrize('stage', RR.STAGES)
def test_each_documented_stage_command_is_accepted_by_its_cli(stage_cli, capsys, stage):
    result = stage_cli(stage, _documented_options()[stage])
    assert isinstance(result, Parsed), capsys.readouterr().err


@pytest.mark.parametrize('stage', ['mosaic', 'package', 'qa'])
def test_stage_command_without_its_options_is_a_usage_error(stage_cli, stage):
    """Control: the per-stage check would catch a row that leaves out required options."""
    result = stage_cli(stage, '')
    assert isinstance(result, SystemExit) and result.code == 2
