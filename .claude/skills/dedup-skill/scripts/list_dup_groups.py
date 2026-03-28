from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _is_exact_duplicate(group: dict[str, Any], repo: Path) -> bool:
    """Check if all occurrences in a group are byte-for-byte identical."""
    fragments: list[str] = []
    for occ in group.get("occurrences", []):
        occ_path_str = occ.get("path", "")
        if occ_path_str.startswith(str(repo)):
            occ_path = Path(occ_path_str)
        else:
            occ_path = repo / occ_path_str
        
        if not occ_path.exists():
            return False
        try:
            content = occ_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            start = max(0, occ.get("start_line", 1) - 1)
            end = min(len(lines), occ.get("end_line", 1))
            snippet = "\n".join(lines[start:end]).strip()
            fragments.append(snippet)
        except Exception:
            return False
    
    if len(fragments) <= 1:
        return True
    return all(item == fragments[0] for item in fragments[1:])


def parse_cpd_xml(xml_path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    groups: list[dict[str, Any]] = []
    duplication_nodes = [node for node in root.iter() if _tag_name(node.tag) == "duplication"]

    for idx, dup in enumerate(duplication_nodes, start=1):
        lines = int(dup.attrib.get("lines", 0))
        tokens = int(dup.attrib.get("tokens", 0))

        occurrences: list[dict[str, Any]] = []
        files: list[str] = []
        for child in dup:
            if _tag_name(child.tag) != "file":
                continue
            raw_path = child.attrib.get("path", "")
            files.append(raw_path)
            line = int(child.attrib.get("line", 1))
            endline_raw = child.attrib.get("endline")
            end_line = int(endline_raw) if endline_raw is not None else line + max(1, lines) - 1
            occurrences.append({
                "path": raw_path,
                "start_line": line,
                "end_line": end_line,
            })

        score = len(occurrences) * max(lines, 1)
        groups.append(
            {
                "id": idx,
                "lines": lines,
                "tokens": tokens,
                "occurrences": occurrences,
                "occurrence_count": len(occurrences),
                "files": sorted(set(files)),
                "score": score,
            }
        )

    groups.sort(key=lambda item: item["score"], reverse=True)
    return groups


def _print_table(groups: list[dict[str, Any]], limit: int) -> None:
    selected = groups[:limit] if limit > 0 else groups
    if not selected:
        print("no duplication groups found")
        return

    header = f"{'ID':<5}{'LINES':<8}{'TOKENS':<8}{'OCC':<6}{'SCORE':<8}FILES"
    print(header)
    print("-" * len(header))
    for item in selected:
        files = ", ".join(item["files"][:3])
        if len(item["files"]) > 3:
            files += " ..."
        print(
            f"{item['id']:<5}{item['lines']:<8}{item['tokens']:<8}{item['occurrence_count']:<6}{item['score']:<8}{files}"
        )
        for idx, occ in enumerate(item.get("occurrences", []), start=1):
            occ_path = occ.get("path", "")
            start_line = occ.get("start_line", 1)
            end_line = occ.get("end_line", start_line)
            print(f"      - occ#{idx}: {occ_path}:{start_line}-{end_line}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="List CPD duplication groups")
    parser.add_argument("xml", type=Path, help="duplication.xml path")
    parser.add_argument("--json", action="store_true", help="Output full json")
    parser.add_argument("--exact-only", action="store_true", help="Filter to show only exact duplicates")
    parser.add_argument("--table-only", action="store_true", help="Print table and exit (no further action)")
    parser.add_argument("--limit", type=int, default=30, help="Table row limit, 0 means all")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root for exact duplicate detection")
    args = parser.parse_args()

    xml_path = args.xml.resolve()
    if not xml_path.exists():
        raise SystemExit(f"xml not found: {xml_path}")

    groups = parse_cpd_xml(xml_path)
    
    repo = args.repo.resolve()
    if args.exact_only:
        filtered = []
        for group in groups:
            if _is_exact_duplicate(group, repo):
                filtered.append(group)
        groups = filtered
        if not groups:
            print("[info] no exact duplicate groups found")
            return 0

    if args.json:
        print(json.dumps(groups, ensure_ascii=False, indent=2))
    else:
        _print_table(groups, args.limit)
    
    if args.table_only:
        print("\n[info] table-only mode: stopping execution without further dedup action")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
