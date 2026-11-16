#!/usr/bin/env python3
"""Rebuild dist/*.zip, MANIFEST.csv and SHA256SUMS.txt for this Skills repo.

Usage:
  python3 scripts/pack-skills.py            # rebuild everything
  python3 scripts/pack-skills.py --check    # verify only, write nothing

Conventions (also documented in README.md):
  source_files   = number of files under skills/<name>/ (recursive)
  source_sha256  = SHA-256 over the concatenation, for each file sorted by
                   relative path, of:  "<relpath>" + 0x00 + "<sha256 of bytes>" + "\n"
  zip            = dist/<name>.zip, entries relative to the skill dir so SKILL.md
                   sits at the zip root; deterministic (fixed timestamp + order)
  zip_sha256     = SHA-256 of the zip bytes
Hashes are uppercase hex, matching the existing manifest.
"""

import argparse
import csv
import hashlib
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
DIST = ROOT / "dist"
MANIFEST = ROOT / "MANIFEST.csv"
SUMS = ROOT / "SHA256SUMS.txt"
FIXED_DT = (1980, 1, 1, 0, 0, 0)
HEADER = ["name", "version", "source_files", "source_sha256", "zip_file", "zip_sha256"]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def skill_dirs():
    return sorted([p for p in SKILLS.iterdir() if p.is_dir()], key=lambda p: p.name)


def files_of(d: Path):
    return sorted(
        [p for p in d.rglob("*") if p.is_file()],
        key=lambda p: p.relative_to(d).as_posix(),
    )


def source_hash(d: Path, files):
    buf = bytearray()
    for p in files:
        rel = p.relative_to(d).as_posix()
        buf += rel.encode() + b"\x00" + hashlib.sha256(p.read_bytes()).hexdigest().encode() + b"\n"
    return sha256_hex(bytes(buf))


def build_zip(d: Path, files, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            rel = p.relative_to(d).as_posix()
            info = zipfile.ZipInfo(rel, FIXED_DT)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())


def read_versions():
    versions = {}
    if MANIFEST.exists():
        text = MANIFEST.read_text(encoding="utf-8-sig")
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("name"):
                versions[row["name"]] = row.get("version") or "not declared"
    return versions


def manifest_text(rows):
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for row in rows:
        writer.writerow([row[k] for k in HEADER])
    return buf.getvalue()


def sums_text(rows):
    return "".join(f"{row['zip_sha256']}  {row['zip_file']}\n" for row in rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = ap.parse_args()

    versions = read_versions()
    rows = []
    problems = []

    for d in skill_dirs():
        name = d.name
        files = files_of(d)
        skill_md = d / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{name}: missing SKILL.md")
            continue
        head = skill_md.read_text(encoding="utf-8", errors="replace")
        if not head.startswith("---"):
            problems.append(f"{name}: SKILL.md has no YAML frontmatter")
        for key in ("name:", "description:"):
            if f"\n{key}" not in head and not head.startswith(key):
                problems.append(f"{name}: frontmatter missing {key.rstrip(':')}")
        zip_path = DIST / f"{name}.zip"
        if args.check:
            if not zip_path.is_file():
                problems.append(f"{name}: missing {zip_path.relative_to(ROOT)}")
                continue
            zip_sha = sha256_hex(zip_path.read_bytes())
        else:
            build_zip(d, files, zip_path)
            zip_sha = sha256_hex(zip_path.read_bytes())
        rows.append(
            {
                "name": name,
                "version": versions.get(name, "not declared"),
                "source_files": len(files),
                "source_sha256": source_hash(d, files),
                "zip_file": f"dist/{name}.zip",
                "zip_sha256": zip_sha,
            }
        )

    expected_manifest = manifest_text(rows)
    expected_sums = sums_text(rows)

    if args.check:
        drift = []
        if not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8-sig") != expected_manifest.lstrip("\ufeff"):
            drift.append("MANIFEST.csv")
        if not SUMS.exists() or SUMS.read_text(encoding="utf-8") != expected_sums:
            drift.append("SHA256SUMS.txt")
        stale = {p.name for p in DIST.glob("*.zip")} - {f"{r['name']}.zip" for r in rows}
        for s in sorted(stale):
            drift.append(f"stale dist/{s}")
        for p in problems:
            print(f"PROBLEM {p}")
        for d in drift:
            print(f"DRIFT   {d}")
        if problems or drift:
            print(f"check failed: {len(problems)} problem(s), {len(drift)} drift item(s)")
            return 1
        print(f"check ok: {len(rows)} skills, manifest and sums match")
        return 0

    with open(MANIFEST, "w", encoding="utf-8", newline="") as f:
        f.write(expected_manifest)
    with open(SUMS, "w", encoding="utf-8") as f:
        f.write(expected_sums)
    for p in problems:
        print(f"PROBLEM {p}")
    print(f"rebuilt {len(rows)} skills -> dist/, MANIFEST.csv, SHA256SUMS.txt")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
