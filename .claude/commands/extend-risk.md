---
description: Extend an existing upgrade risk to a new target release
---

You are helping extend an existing upgrade risk declaration to a new target release.

## Arguments

Usage: `/extend-risk <risk-name> <current-version> <new-version>`

- `$1` - Risk name (e.g., `RuncShareProcessNamespace`)
- `$2` - Current version the risk affects (e.g., `4.14.59`)
- `$3` - New version to extend the risk to (e.g., `4.14.60`)

Example: `/extend-risk RuncShareProcessNamespace 4.14.59 4.14.60`

## Task

1. Read the source file `blocked-edges/$2-$1.yaml`:
   - This is the existing risk declaration for version `$2`
   - If the file doesn't exist, report an error to the user

2. Create new file `blocked-edges/$3-$1.yaml`:
   - Copy all content from `blocked-edges/$2-$1.yaml`
   - Update only the `to:` field from `$2` to `$3`
   - Keep all other fields unchanged: `from`, `url`, `name`, `message`, `matchingRules`, `fixedIn`, `autoExtend`
   - Preserve exact YAML formatting

3. Validate:
   - If `fixedIn` is set and `$3` >= `fixedIn`, warn that this risk may already be fixed
   - Verify the `from` regex pattern is appropriate for `$3`

4. Report:
   - Source file: `blocked-edges/$2-$1.yaml`
   - New file: `blocked-edges/$3-$1.yaml`
   - Show diff (only `to:` field should change)
   - Suggested commit: `blocked-edges: extend $1 to $3`

## Notes

- Do NOT modify the source file
- Only change the `to:` field value
- Preserve all YAML formatting