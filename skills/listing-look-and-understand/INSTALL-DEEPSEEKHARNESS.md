# DeepSeekHarness Skill package — listing-look-and-understand 1.1.1

This archive has `SKILL.md` at its root, followed by the scripts, references, requirements, and behavior tests. If DeepSeekHarness has a custom Skill import action, import this ZIP there. Otherwise, extract the archive into a directory named `listing-look-and-understand` under its Skills directory, keeping `SKILL.md` at that directory's root.

## Requirements

- Python 3.10 or newer.
- Offline HTML parsing: install `requirements.txt`.
- Online capture: install `requirements-online.txt`, have Microsoft Edge on Windows or Chrome/Chromium on Linux, and use a runtime that permits browser automation. Driver download may require network access; no browser, driver, cookies, or Amazon account session is included.
- When online access or browser launch is restricted, use the documented offline HTML import workflow. The Skill does not bypass network or browser security controls.

## Verify the package

From the extracted Skill directory, run `python -m unittest discover -s tests -v`.

This is a portable folder-based Agent Skill package. No DeepSeekHarness-specific installer API was available to validate here.
