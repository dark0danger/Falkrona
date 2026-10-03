"""Generate the locked Phase 1 dependency and declared-license inventory."""

from __future__ import annotations

from datetime import date
from importlib import metadata
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "DEPENDENCY_LICENSES.md"


def python_license(distribution: metadata.Distribution) -> str:
    expression = distribution.metadata.get("License-Expression")
    if expression:
        return expression.strip()
    declared = distribution.metadata.get("License", "").strip()
    if declared and declared.upper() != "UNKNOWN" and "\n" not in declared and len(declared) < 120:
        return declared
    classifiers = [
        value.removeprefix("License :: ")
        for value in distribution.metadata.get_all("Classifier", [])
        if value.startswith("License :: ")
    ]
    return "; ".join(classifiers) or "NOT DECLARED"


def python_rows() -> list[tuple[str, str, str]]:
    rows = []
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name") or "unknown"
        rows.append((name, distribution.version, python_license(distribution)))
    return sorted(set(rows), key=lambda row: row[0].lower())


def node_rows() -> list[tuple[str, str, str]]:
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    rows = []
    for path, package in lock.get("packages", {}).items():
        if "node_modules/" not in path or not package.get("version"):
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        license_name = package.get("license") or "NOT DECLARED"
        rows.append((name, package["version"], license_name))
    return sorted(set(rows), key=lambda row: row[0].lower())


def table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Package | Version | Declared license |", "| --- | --- | --- |"]
    lines.extend(
        f"| `{name}` | `{version}` | {license_name.replace('|', '/')} |"
        for name, version, license_name in rows
    )
    return "\n".join(lines)


def main() -> int:
    python = python_rows()
    node = node_rows()
    content = f"""# Dependency License Inventory

Generated on {date.today().isoformat()} from the Phase 1 locked environment.

This inventory records package-declared metadata. `NOT DECLARED` requires manual
review before distribution. Lockfiles remain authoritative for hashes and exact
resolution.

## Python ({len(python)})

{table(python)}

## Node ({len(node)})

{table(node)}
"""
    OUTPUT.write_text(content, encoding="utf-8")
    missing = [row for row in python + node if row[2] == "NOT DECLARED"]
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "python_packages": len(python),
                "node_packages": len(node),
                "licenses_not_declared": len(missing),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
