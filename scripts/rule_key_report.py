#!/usr/bin/env python3
"""Render the built clause indexes as a reviewable citation → rule key table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def render_report(site: Path, text_limit: int = 80) -> str:
    manifest = json.loads((site / "rules-manifest.json").read_text(encoding="utf-8"))
    lines = ["# Stable rule keys", ""]
    for document in manifest["documents"]:
        index = json.loads((site / document["index_path"]).read_text(encoding="utf-8"))
        rules = index["rules"]
        keyed = [rule for rule in rules if "rule_key" in rule]
        lines.append(f'## {document["document"]} {document["version"]}')
        lines.append("")
        lines.append(f"{len(keyed)} / {len(rules)} indexed clauses carry a stable key.")
        lines.append("")
        lines.append("| Citation | Clause ID | Rule key | Text |")
        lines.append("| --- | --- | --- | --- |")
        for rule in rules:
            text = rule["text"].replace("|", "\\|")
            if len(text) > text_limit:
                text = text[: text_limit - 1] + "…"
            lines.append(f'| {rule["citation"]} | `{rule["id"]}` | `{rule.get("rule_key", "")}` | {text} |')
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT / "_site")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(render_report(args.site), encoding="utf-8")
    print(f"규정 키 보고서 생성: {args.output}")


if __name__ == "__main__":
    main()
