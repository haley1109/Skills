# Skills repository

This repository stores one source folder per Agent Skill under `skills/` and one portable ZIP per Skill under `dist/`. Each ZIP has `SKILL.md` at its root.

The library includes the original 90 Haley personal skills, `amazon-us-launch`, and [amazon-keyword-workbook](skills/amazon-keyword-workbook/SKILL.md) for building an Amazon keyword workbook from ABA, competitor traffic, and search-result evidence. `listing-look-and-understand` is version 1.1.1. The public Amazon US Skill contains an empty `references/project-memory.md` template; private TOPWAVE preferences and case notes are omitted. No Amazon page captures, browser profiles, credentials, or account tokens are included.

Many Skills depend on host tools, connected services, network access, or local packages that are not bundled here. Copying the instruction files does not transfer those integrations or permissions.

## Maintenance

1. Edit the source under `skills/<skill-name>/` (and its `references/`).
2. Rebuild packaging: `python3 scripts/pack-skills.py`
3. Verify without writing: `python3 scripts/pack-skills.py --check`
4. Commit `skills/`, `dist/`, `MANIFEST.csv`, and `SHA256SUMS.txt` together.
5. Fetch and compare the remote branch before pushing so existing repository work is preserved.

Packaging rules (implemented by `scripts/pack-skills.py`):

- `source_files` — number of files under `skills/<name>/`, recursive.
- `source_sha256` — SHA-256 over, for each file sorted by relative path, `"<relpath>" + NUL + "<sha256 of file bytes, lowercase hex>" + "\n"`. Uppercase hex in the manifest.
- `dist/<name>.zip` — entries are relative to the skill directory, so `SKILL.md` sits at the zip root. Zips are deterministic (sorted entries, fixed 1980-01-01 timestamp), so rebuilding unchanged sources reproduces identical bytes.
- `zip_sha256` — SHA-256 of the zip bytes, uppercase.
- `version` is carried over from the previous manifest; new skills default to `not declared`.

`scripts/pack-skills.py --check` fails on a missing `SKILL.md`, missing frontmatter `name`/`description`, a missing zip, stale zips, or a manifest/sums mismatch.
