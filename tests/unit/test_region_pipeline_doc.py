"""docs/region-pipeline.md lists the mapping chain as one command per stage, in the runner's order."""
import re

from scripts.relief import run_region as RR
from tests._support import ROOT

DOC = ROOT / 'docs' / 'region-pipeline.md'
BEGIN, END = '<!-- mapping-chain-stages:begin -->', '<!-- mapping-chain-stages:end -->'
SECTION = re.compile(r'^## Mapping chain: one command per stage$(.*?)^## ', re.M | re.S)
LINK = re.compile(r'\]\(([^)#]+)(?:#[^)]*)?\)')


def _section():
    match = SECTION.search(DOC.read_text(encoding='utf-8'))
    assert match, 'region-pipeline.md has no "Mapping chain: one command per stage" section'
    return match.group(1)


def _stage_rows(section):
    table = section.split(BEGIN, 1)[1].split(END, 1)[0]
    return [line for line in table.splitlines() if line.startswith('| `')]


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
