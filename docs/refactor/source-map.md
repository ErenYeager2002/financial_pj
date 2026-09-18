# Source map

Baseline `2cd58e91348ff566250f03b882f22c46425bbe1f`. Static AST evidence only; dynamic dispatch, imported aliases and runtime reachability require targeted verification.

Tracked baseline source is indexed by path, symbol and exact line span in [source-inventory.json](reports/source-inventory.json). [source-inventory.md](reports/source-inventory.md) is the file index. TypeScript symbols use the compiler AST report. Untracked code, environment files, runtime data and symlinks are intentionally excluded.

The refactor worktree is separate from the deployed release. Changes in the deployed non-Git tree are not automatically copied here; they require provenance and compatibility review. Generated/vendor flags are conservative hints, not permission to modify or delete.
