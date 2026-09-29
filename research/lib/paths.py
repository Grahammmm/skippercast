"""Repository locations for research scripts.

Research scripts used to import ``ROOT`` from an unrelated sibling audit script
(for example ``from scripts.audit_csumb_bss_native import ROOT``), which tied
unrelated audits together. Import it from here instead.
"""
from pathlib import Path

# research/lib/paths.py -> repository root
ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / 'research'
