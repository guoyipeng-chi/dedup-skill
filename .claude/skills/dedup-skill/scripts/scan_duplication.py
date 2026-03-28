from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _find_pmd_bin(explicit: str | None, workspace: Path) -> str:
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit))

    env_bin = os.environ.get("PMD_BIN")
    if env_bin:
        candidates.append(Path(env_bin))

    tools_dir = workspace / ".tools"
    if tools_dir.exists():
        for item in tools_dir.glob("pmd-bin-*/bin/*"):
            if item.name.lower() in {"pmd", "pmd.bat", "pmd.cmd"}:
                candidates.append(item)

    direct = shutil.which("pmd")
    if direct:
        candidates.append(Path(direct))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        "未找到 PMD 可执行文件。请通过 --pmd 指定，或设置 PMD_BIN，或将 pmd 放到 PATH/.tools。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PMD CPD scan and produce duplication XML.")
    parser.add_argument("repo", type=Path, help="Repository path to scan")
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts"), help="Output folder")
    parser.add_argument("--out-file", type=str, default="duplication.xml", help="Output xml filename")
    parser.add_argument("--min-tokens", type=int, default=40, help="Minimum token threshold")
    parser.add_argument("--language", type=str, default="cpp", help="CPD language (cpp, java, etc.)")
    parser.add_argument("--pmd", type=str, default=None, help="Path to pmd executable")
    parser.add_argument("--encoding", type=str, default="utf-8", help="Source encoding")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"repo path 不存在或不是目录: {repo}")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_xml = out_dir / args.out_file
    out_xml_with_ts = out_dir / f"duplication_{timestamp}.xml"

    pmd_bin = _find_pmd_bin(args.pmd, Path.cwd())

    base = [
        pmd_bin,
        "cpd",
        "--minimum-tokens",
        str(args.min_tokens),
        "--format",
        "xml",
        "--language",
        args.language,
        "--encoding",
        args.encoding,
        "--skip-lexical-errors",
    ]

    cmd_variants = [
        base + ["--files", str(repo)],
        base + ["--dir", str(repo)],
    ]

    proc = None
    xml_text = ""
    for idx, cmd in enumerate(cmd_variants, start=1):
        print(f"[scan] running variant {idx}:", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        candidate = (proc.stdout or "").strip()
        if candidate.startswith("<?xml") or "<pmd-cpd" in candidate:
            xml_text = candidate
            break
        if proc.returncode == 0:
            xml_text = candidate
            break

    if proc is None:
        raise SystemExit(1)

    if proc.returncode != 0 and not xml_text:
        if proc is not None:
            sys.stderr.write(proc.stderr or "")
            sys.stderr.write(proc.stdout or "")
            raise SystemExit(proc.returncode)

    if not xml_text:
        raise SystemExit("CPD 输出为空，未生成 duplication XML。")

    out_xml.write_text(xml_text, encoding="utf-8")
    out_xml_with_ts.write_text(xml_text, encoding="utf-8")

    print(f"[scan] xml: {out_xml}")
    print(f"[scan] xml(timestamped): {out_xml_with_ts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
