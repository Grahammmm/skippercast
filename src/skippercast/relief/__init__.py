"""Relief pipeline: one raw-to-live path for depth shading, contours, detail labels and 3D.

Design: ``reports/sc-map-goal/E2E-PIPELINE.md`` (agent-work). Every data transform is a
*stage* module ``skippercast.relief.<stage>``; ``scripts/relief/region.py <stage>`` finds
it by name, so a new stage is a new module and never an edit to the CLI.

A stage module provides either

* ``build(ctx, out_dir) -> dict | None`` (a receipt stage, run by
  :func:`skippercast.relief.receipts.run_stage`), with the optional attributes
  ``UPSTREAM`` (``"stage"`` or ``"stage:scope"``; ``{scope}`` is replaced by the run's
  scope), ``SCOPES``, ``TARGET``, ``CODE_FILES``, ``add_arguments(parser)`` and
  ``plan(ctx) -> Plan``; or
* ``main(argv) -> int`` for a command that manages its own receipts (publish,
  live-check, rollback).

Stage state lives in ``OUT/<region>/stages/<stage>.json`` (schema ``sc-stage-receipt/1``);
:mod:`skippercast.relief.receipts` owns its format, the generation hash and the "done" rule.
"""
