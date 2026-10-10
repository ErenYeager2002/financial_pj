# Balance.38 source baseline before Hub migration

Version: `1.6.24-lab.6.local.35.sales.9.balance.38`

This checkpoint records the deployed reconciliation changes and the scoped
release helper. It provides a fixed source baseline before future Hub migration.
No Hub cutover or financial-task rerun is part of this synchronization.

## Included changes

- Apply SO-level settlement-tail evidence once when several SOD lines share it.
- Quarantine inferred allocations that conflict with explicit source evidence.
- Match uniquely supported merged bank receipts with amount-conservation and
  ambiguity checks, retaining manual review for uncertain matches.
- Clear arrival-flow filters before appending below the last business record,
  preserving existing rows and validating the saved workbook.
- Retain strict image configuration and filesystem equivalence checks in the
  scoped release helper, including validation of reused flattened images.

## Verification boundary

The 23 changed Skill-package files match the deployed API package and the frozen
source from the accepted release. The scoped release helper also matches that
frozen source. The release previously passed 545 targeted regression tests.
This Git synchronization adds static diff review, Python syntax checks, staged
content review, and source/runtime hash comparisons. It does not represent a new
full test run, a new deployment, or GitHub CI verification.

Split-remittance remark handling remains outside this release and retains manual
review. Uncertain allocation or non-unique arrival matches remain pending review.
Business workbooks, credentials, and operational diagnostic reports are excluded
from this checkpoint.
