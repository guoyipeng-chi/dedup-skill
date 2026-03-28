from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path


def _auto_install_pmd(tools_dir: Path) -> str:
    """Try to auto-install PMD from official GitHub release."""
    print("[pmd] PMD not found. Attempting auto-install...")
    pmd_version = "7.22.0"
    download_url = f"https://github.com/pmd/pmd/releases/download/pmd_releases%2F{pmd_version}/pmd-bin-{pmd_version}.zip"
    
    try:
        pmd_dir = tools_dir / f"pmd-bin-{pmd_version}"
        if pmd_dir.exists():
            print(f"[pmd] using existing installation at {pmd_dir}")
            return _find_pmd_in_dir(pmd_dir)
        
        print(f"[pmd] downloading PMD {pmd_version} from GitHub...")
        tools_dir.mkdir(parents=True, exist_ok=True)
        zip_path = tools_dir / f"pmd-{pmd_version}.zip"
        
        urllib.request.urlretrieve(download_url, zip_path)
        print(f"[pmd] download complete, extracting...")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(tools_dir)
        
        zip_path.unlink()
        pmd_bin = _find_pmd_in_dir(pmd_dir)
        print(f"[pmd] auto-install success: {pmd_bin}")
        return pmd_bin
    except Exception as e:
        raise RuntimeError(
            f"PMD auto-install failed: {e}\n"
            f"解决方案：\n"
            f"  1. 手动指定: python scan_duplication.py <repo> --pmd <pmd_path>\n"
            f"  2. 环境变量: SET PMD_BIN=<pmd_path>\n"
            f"  3. 禁用自动安装: python scan_duplication.py <repo> --no-auto-install-pmd\n"
            f"  4. 手动下载: https://pmd.github.io/latest/pages/installation.html"
        )


def _find_pmd_in_dir(pmd_dir: Path) -> str:
    """Find pmd executable in a PMD installation directory."""
    for item in pmd_dir.glob("**/bin/*"):
        if item.name.lower() in {"pmd", "pmd.bat", "pmd.cmd"}:
            return str(item)
    raise FileNotFoundError(f"PMD executable not found in {pmd_dir}")


def _find_pmd_bin(explicit: str | None, workspace: Path, auto_install: bool = True) -> str:
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

    if auto_install:
        return _auto_install_pmd(workspace / ".tools")
    
    raise FileNotFoundError(
        "未找到 PMD 可执行文件。\n"
        "解决方案：\n"
        "  1. 手动指定路径:       python scan_duplication.py <repo> --pmd <pmd_path>\n"
        "  2. 设置环境变量:       SET PMD_BIN=<pmd_path>\n"
        "  3. 启用自动安装:       python scan_duplication.py <repo>\n"
        "  4. 禁用自动安装:       python scan_duplication.py <repo> --no-auto-install-pmd\n"
        "  5. 手动下载安装:       https://pmd.github.io/latest/pages/installation.html"
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
    parser.add_argument("--no-auto-install-pmd", action="store_true", help="Disable automatic PMD installation")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"repo path 不存在或不是目录: {repo}")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_xml = out_dir / args.out_file
    out_xml_with_ts = out_dir / f"duplication_{timestamp}.xml"

    pmd_bin = _find_pmd_bin(args.pmd, Path.cwd(), auto_install=not args.no_auto_install_pmd)

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
