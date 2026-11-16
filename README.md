# Skills repository

This repository stores one source folder per Agent Skill under `skills/` and one portable ZIP per Skill under `dist/`. Each ZIP has `SKILL.md` at its root.

Current scope: 90 Haley personal skill library entries and the separate `amazon-us-launch` workspace Skill. `listing-look-and-understand` is version 1.1.1. The public Amazon US Skill contains an empty `references/project-memory.md` template; private TOPWAVE preferences and case notes are omitted. No Amazon page captures, browser profiles, credentials, or account tokens are included.

Many Skills depend on host tools, connected services, network access, or local packages that are not bundled here. Copying the instruction files does not transfer those integrations or permissions.

For ongoing maintenance, update source under `skills/<skill-name>/`, run its available checks, rebuild the matching `dist/<skill-name>.zip`, and update `MANIFEST.csv` and `SHA256SUMS.txt` before committing and pushing. Fetch and compare the remote branch before each update so existing repository work is preserved.
