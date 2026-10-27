// Baseline registers exactly the same two tests as the repaired focused suite.
process.argv.push('--sp1506-baseline');
await import('../../test_sp1506_field_provenance.mjs');
