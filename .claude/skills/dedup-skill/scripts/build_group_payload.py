from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_groups(xml_path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    groups: list[dict[str, Any]] = []
    duplication_nodes = [node for node in root.iter() if _tag_name(node.tag) == "duplication"]

    for idx, dup in enumerate(duplication_nodes, start=1):
        lines = int(dup.attrib.get("lines", 0))
        tokens = int(dup.attrib.get("tokens", 0))
        occs: list[dict[str, Any]] = []
        for child in dup:
            if _tag_name(child.tag) != "file":
                continue
            line = int(child.attrib.get("line", 1))
            endline_raw = child.attrib.get("endline")
            end_line = int(endline_raw) if endline_raw is not None else line + max(1, lines) - 1
            occs.append(
                {
                    "path": child.attrib.get("path", ""),
                    "start_line": line,
                    "end_line": end_line,
                }
            )

        fragment_node = next((item for item in dup if _tag_name(item.tag) == "codefragment"), None)
        fragment = (fragment_node.text or "").strip("\n") if fragment_node is not None else ""

        groups.append(
            {
                "id": idx,
                "lines": lines,
                "tokens": tokens,
                "occurrence_count": len(occs),
                "score": len(occs) * max(lines, 1),
                "code_fragment": fragment,
                "occurrences": occs,
            }
        )

    return groups


def _resolve_repo_path(repo: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (repo / path).resolve()


def _slice_lines(file_path: Path, start_line: int, end_line: int, window: int) -> dict[str, Any]:
    if not file_path.exists():
        return {
            "exists": False,
            "selected": "<file not found>",
            "before": "<empty>",
            "after": "<empty>",
            "total_lines": 0,
        }

    lines = file_path.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    start = max(1, start_line)
    end = min(total, max(start, end_line))

    before_start = max(1, start - window)
    after_end = min(total, end + window)

    before = "\n".join(f"{i}|{lines[i-1]}" for i in range(before_start, start)) or "<empty>"
    selected = "\n".join(f"{i}|{lines[i-1]}" for i in range(start, end + 1)) or "<empty>"
    after = "\n".join(f"{i}|{lines[i-1]}" for i in range(end + 1, after_end + 1)) or "<empty>"

    return {
        "exists": True,
        "selected": selected,
        "before": before,
        "after": after,
        "total_lines": total,
    }


def _parse_group_ids(value: str) -> set[int]:
    ids: set[int] = set()
    for chunk in value.split(","):
        text = chunk.strip()
        if not text:
            continue
        ids.add(int(text))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description="Build selected duplication group payload with code context")
    parser.add_argument("xml", type=Path, help="duplication.xml path")
    parser.add_argument("--repo", type=Path, default=Path("."), help="repository root")
    parser.add_argument("--groups", type=str, required=True, help="comma separated group ids, e.g. 1,3")
    parser.add_argument("--window", type=int, default=5, help="context lines around selected range")
    parser.add_argument("--out", type=Path, default=Path("artifacts/selected_groups_payload.json"), help="output payload file")
    args = parser.parse_args()

    xml_path = args.xml.resolve()
    if not xml_path.exists():
        raise SystemExit(f"xml not found: {xml_path}")

    repo = args.repo.resolve()
    selected_ids = _parse_group_ids(args.groups)
    groups = parse_groups(xml_path)

    selected_groups = [item for item in groups if item["id"] in selected_ids]
    if not selected_groups:
        raise SystemExit(f"no groups matched: {sorted(selected_ids)}")

    payload: dict[str, Any] = {
        "repo": str(repo),
        "xml": str(xml_path),
        "selected_group_ids": sorted(selected_ids),
        "groups": [],
    }

    for group in selected_groups:
        group_out = {
            "id": group["id"],
            "lines": group["lines"],
            "tokens": group["tokens"],
            "occurrence_count": group["occurrence_count"],
            "score": group["score"],
            "code_fragment": group["code_fragment"],
            "occurrences": [],
        }

        for occ in group["occurrences"]:
            full_path = _resolve_repo_path(repo, occ["path"])
            context = _slice_lines(full_path, int(occ["start_line"]), int(occ["end_line"]), args.window)
            group_out["occurrences"].append(
                {
                    "path": occ["path"],
                    "absolute_path": str(full_path),
                    "start_line": occ["start_line"],
                    "end_line": occ["end_line"],
                    **context,
                }
            )

        payload["groups"].append(group_out)

    out_path = args.out.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"payload written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
