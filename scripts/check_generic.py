#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ok = True
    issues = []

    # 1) No app instances in capsule/ (only 'reports' allowed)
    cap = root / 'capsule'
    if cap.exists():
        for p in cap.iterdir():
            if p.is_dir() and p.name != 'reports':
                ok = False
                issues.append(f"capsule contains non-reports dir: {p}")

    # 2) No validation .run_tmp
    if (root / 'capsule' / 'reports' / 'validation' / '.run_tmp').exists():
        ok = False
        issues.append("validation/.run_tmp present")

    # 3) No duplicate packager scripts outside tools/final_bundle/*
    dup_py = root / 'tools' / 'verify_and_package.py'
    dup_sh = root / 'tools' / 'verify_and_package.sh'
    if dup_py.exists() or dup_sh.exists():
        ok = False
        issues.append("duplicate verify_and_package.* found under tools/")

    # 4) No hardcoded app namespace in engine code (exclude templates/tools/prompts/schemas/validation/README.md)
    allow_prefixes = {
        (root / 'templates'),
        (root / 'tools'),
        (root / 'prompts'),
        (root / 'schemas'),
        (root / 'capsule' / 'reports' / 'validation'),
    }
    allow_files = {root / 'README.md'}
    pattern = re.compile(r'\bautomatr\b', re.I)
    for dirpath, _, filenames in os.walk(root):
        d = Path(dirpath)
        if any(str(d).startswith(str(ap)) for ap in allow_prefixes):
            continue
        for fn in filenames:
            fp = d / fn
            if fp in allow_files or '.git' in fp.parts:
                continue
            try:
                txt = fp.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if pattern.search(txt):
                ok = False
                issues.append(f"unexpected 'automatr' in {fp}")

    print("== Engine Genericity Check ==")
    if ok:
        print("PASS: engine is generic and clean")
        return 0
    else:
        print("FAIL:")
        for i in issues:
            print(" -", i)
        return 1


if __name__ == '__main__':
    sys.exit(main())

