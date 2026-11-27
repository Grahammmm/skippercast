"""The two markers around the generated data-sources register in dist/sources.html.

Import-light on purpose: the stage-preview controller (scripts/relief/morro_stage_controller.py) runs
from a sparse checkout that carries src/skippercast/ but not scripts/build_sources_register.py, and it
only needs these markers to check that a candidate changes the page inside the register block alone.
"""

BEGIN = '<!-- BEGIN GENERATED data-sources: scripts/build_sources_register.py (do not edit by hand) -->'
END = '<!-- END GENERATED data-sources -->'
