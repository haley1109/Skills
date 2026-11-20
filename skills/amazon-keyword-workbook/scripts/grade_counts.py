"""Regrade mutually exclusive product counts using this project's explicit thresholds."""
import argparse
import json
from decimal import Decimal
from pathlib import Path


def percentage(value):
    number = Decimal(value)
    if not number.is_finite() or not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 100")
    return number


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("observations", type=Path, help="JSON array with keyword, basis, observedAt, verySimilar, similar, dissimilar, unknown")
    p.add_argument("result", type=Path, help="new JSON file of counted rows only")
    for tier in ("strong", "related"):
        p.add_argument("--" + tier, required=True, type=percentage, help="inclusive percentage threshold")
        p.add_argument("--" + tier + "-count", required=True, choices=("very", "both"))
    args = p.parse_args()
    if args.strong < args.related:
        p.error("strong threshold must be at least the related threshold")
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    if not isinstance(observations, list):
        p.error("expected an array of observations")

    seen = set()
    result = []
    for row in observations:
        keyword = row["keyword"]
        if not isinstance(keyword, str) or not keyword.strip() or keyword in seen:
            p.error(f"empty or repeated keyword {keyword!r}")
        seen.add(keyword)
        if any(not isinstance(row.get(f), str) or not row[f].strip() for f in ("basis", "observedAt")):
            p.error(f"missing source or observation time for {keyword!r}")
        counts = [row[k] for k in ("verySimilar", "similar", "dissimilar", "unknown")]
        if any(type(x) is not int or x < 0 for x in counts) or sum(counts) == 0:
            p.error(f"invalid counts for {keyword!r}")
        very, similar, _, unknown = counts
        total = sum(counts)
        def grade(extra):
            for label, choice, threshold in (
                ("强相关", args.strong_count, args.strong),
                ("相关", args.related_count, args.related),
            ):
                numerator = very + (similar if choice == "both" else 0) + extra
                if numerator * 100 >= threshold * total:
                    return label
            return "不相关"
        lower, upper = grade(0), grade(unknown)
        basis = row["basis"] + ("（下限）" if lower != upper else "")
        result.append({**row, "basis": basis, "grade": lower, "upperGrade": upper, "total": total})
    rule = {
        "strongPercent": str(args.strong), "strongCount": args.strong_count,
        "relatedPercent": str(args.related), "relatedCount": args.related_count,
        "denominator": "all", "comparison": ">=",
    }
    with args.result.open("x", encoding="utf-8") as handle:
        json.dump({"rule": rule, "rows": result}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
