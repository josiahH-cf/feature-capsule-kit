#!/usr/bin/env python3
import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _engine_root() -> Path:
    return Path(__file__).resolve().parent


def _app_root() -> Path:
    # engine_root/../.. -> app repo root
    return _engine_root().parent.parent.resolve()


def _load_config(app_root: Path) -> dict:
    cfg = {
        "project": {"namespace": ""},
        "paths": {"features": "", "capsule": "", "final_docs": "", "planning": ""},
    }
    cfg_path = app_root / "capsule.project.toml"
    if not cfg_path.exists():
        raise SystemExit(f"ERROR: missing config: {cfg_path}")

    section = None
    with cfg_path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^\[([^\]]+)\]$", line)
            if m:
                section = m.group(1).strip()
                continue
            m = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+)$", line)
            if m and section:
                key, val = m.group(1), m.group(2).strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if section in cfg and key in cfg[section]:
                    cfg[section][key] = val
    ns = cfg["project"].get("namespace", "").strip()
    if not ns:
        raise SystemExit("ERROR: [project].namespace missing in capsule.project.toml")
    for k in ("features", "capsule", "final_docs", "planning"):
        if not cfg["paths"].get(k, "").strip():
            raise SystemExit(f"ERROR: [paths].{k} missing in capsule.project.toml")
    return cfg


def _replace_tokens_in_file(path: Path, token_map: dict):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return
    for k, v in token_map.items():
        text = text.replace(k, v)
    path.write_text(text, encoding="utf-8")


def _rename_placeholders(root: Path, token_map: dict):
    # Depth-first rename so child paths rename first
    for p in sorted(root.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        new_name = p.name
        for k, v in token_map.items():
            if k in ("{{FEATURE_ID}}", "{{PROJECT_NAMESPACE}}"):
                new_name = new_name.replace(k, v)
        if new_name != p.name:
            p.rename(p.with_name(new_name))


def _render_template(template_dir: Path, feature_id: str, namespace: str, version: str, updated_date: str) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"feature-{feature_id}-"))
    dst = tmpdir / "src"
    shutil.copytree(template_dir, dst)
    token_map = {
        "{{FEATURE_ID}}": feature_id,
        "{{PROJECT_NAMESPACE}}": namespace,
        "{{VERSION}}": version,
        "{{UPDATED_DATE}}": updated_date,
    }
    for f in dst.rglob("*"):
        if f.is_file():
            _replace_tokens_in_file(f, token_map)
    _rename_placeholders(dst, token_map)
    return dst


def _run_validate(feature_id: str, doc: str = None, require_implementable: bool = False) -> int:
    script = _engine_root() / "capsule" / "reports" / "validation" / "validate_all.sh"
    env = os.environ.copy()
    env["FEATURE_ID"] = feature_id
    if doc:
        env["DOC_PATH"] = doc
    if require_implementable:
        env["REQUIRE_IMPLEMENTABLE"] = "1"
    proc = subprocess.run(["bash", str(script)], env=env)
    return proc.returncode


def _gated_copy_and_validate(
    tmp_src: Path,
    feature_id: str,
    dest_capsule: Path,
    dest_features: Path,
    force: bool = False,
    require_implementable: bool = False,
) -> int:
    """
    Copy into place with rollback on validation failure.

    Strategy:
    - Prepare new content under sibling ".__new" dirs
    - If existing, move current to ".__old" and swap in new
    - Run validators; on failure, rollback and return nonzero
    - On success, remove "__old" backups
    """
    cap_src = tmp_src / "capsule" / feature_id
    feat_src = tmp_src / "features" / feature_id

    # Prepare new dirs
    cap_new = dest_capsule.with_name(dest_capsule.name + ".__new")
    feat_new = dest_features.with_name(dest_features.name + ".__new")
    for d in (cap_new, feat_new):
        if d.exists():
            shutil.rmtree(d)

    if cap_src.exists():
        cap_new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(cap_src, cap_new)
    if feat_src.exists():
        feat_new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(feat_src, feat_new)

    # Compute backups if needed
    cap_old = dest_capsule.with_name(dest_capsule.name + ".__old")
    feat_old = dest_features.with_name(dest_features.name + ".__old")
    for d in (cap_old, feat_old):
        if d.exists():
            shutil.rmtree(d)

    # If destinations exist
    if dest_capsule.exists() or dest_features.exists():
        if not force:
            print("ERROR: destination exists; use --force to overwrite", file=sys.stderr)
            # Cleanup staged new dirs
            for d in (cap_new, feat_new):
                if d.exists():
                    shutil.rmtree(d)
            return 2
        # Move current to __old and put __new in place
        if dest_capsule.exists():
            dest_capsule.rename(cap_old)
        if cap_new.exists():
            cap_new.rename(dest_capsule)
        if dest_features.exists():
            dest_features.rename(feat_old)
        if feat_new.exists():
            feat_new.rename(dest_features)
    else:
        # No existing; just move __new into place
        if cap_new.exists():
            cap_new.rename(dest_capsule)
        if feat_new.exists():
            feat_new.rename(dest_features)

    # Validate
    rc = _run_validate(feature_id, None, require_implementable)
    print("Validation:", "PASS" if rc == 0 else f"FAIL (exit {rc})")
    if rc != 0:
        # Rollback: remove new and restore old if present
        if dest_capsule.exists():
            shutil.rmtree(dest_capsule)
        if cap_old.exists():
            cap_old.rename(dest_capsule)
        if dest_features.exists():
            shutil.rmtree(dest_features)
        if feat_old.exists():
            feat_old.rename(dest_features)
        return rc

    # Success: remove backups
    for d in (cap_old, feat_old):
        if d.exists():
            shutil.rmtree(d)
    return 0


def cmd_new(args):
    engine_root = _engine_root()
    app_root = _app_root()
    cfg = _load_config(app_root)

    template_rel = args.from_template or "templates/feature-capsule/feature-template"
    template_dir = (engine_root / template_rel).resolve()
    if not template_dir.is_dir():
        raise SystemExit(f"ERROR: template not found: {template_dir}")

    version = args.version or "0.1.0"
    updated = args.date or _dt.date.today().isoformat()

    dest_capsule = (app_root / cfg["paths"]["capsule"] / args.feature_id).resolve()
    dest_features = (app_root / cfg["paths"]["features"] / args.feature_id).resolve()

    print("== New Feature ==")
    print(f"Feature ID: {args.feature_id}")
    print(f"Template:   {template_dir}")
    print(f"Namespace:  {cfg['project']['namespace']}")
    print(f"Dest(caps): {dest_capsule}")
    print(f"Dest(feat): {dest_features}")

    if args.dry_run:
        print("DRY-RUN: would render, validate, and copy to destinations")
        return 0

    tmp_src = _render_template(template_dir, args.feature_id, cfg["project"]["namespace"], version, updated)

    # Copy with validation gate and rollback
    rc = _gated_copy_and_validate(tmp_src, args.feature_id, dest_capsule, dest_features, force=args.force, require_implementable=False)
    return rc


def cmd_validate(args):
    rc = _run_validate(args.feature_id, args.doc, bool(args.require_implementable))
    return rc


def cmd_package(args):
    engine_root = _engine_root()
    script = engine_root / "tools" / "final_bundle" / "verify_and_package.sh"
    if not script.exists():
        print(f"ERROR: packager not found: {script}", file=sys.stderr)
        return 2
    allow = str(args.allow_gt_1600).lower()
    if allow not in ("yes", "no"):
        print("ERROR: --allow-gt-1600 must be yes|no", file=sys.stderr)
        return 2
    proc = subprocess.run(["bash", str(script), f"feature_id={args.feature_id}", f"allow_gt_1600_tokens={allow}"])
    return proc.returncode


def cmd_info(_args):
    engine_root = _engine_root()
    app_root = _app_root()
    try:
        cfg = _load_config(app_root)
    except SystemExit as e:
        print(str(e))
        cfg = None
    print("Engine root:", engine_root)
    print("App root:", app_root)
    if cfg:
        print("Namespace:", cfg["project"]["namespace"]) 
        print("Paths:")
        for k, v in cfg["paths"].items():
            print(f"  {k}: {v}")
        tpath = engine_root / "templates/feature-capsule/feature-template"
        print("Template:", tpath)
        print("Destinations (resolved):")
        print("  capsule:", (app_root / cfg["paths"]["capsule"]).resolve())
        print("  features:", (app_root / cfg["paths"]["features"]).resolve())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="capsule-engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="create a new feature from template")
    p_new.add_argument("--feature-id", required=True)
    p_new.add_argument("--from-template", default=None)
    p_new.add_argument("--version", default=None)
    p_new.add_argument("--date", dest="date", default=None)
    p_new.add_argument("--dry-run", action="store_true")
    p_new.add_argument("--force", action="store_true")
    p_new.set_defaults(func=cmd_new)

    p_val = sub.add_parser("validate", help="run validators")
    p_val.add_argument("--feature-id", required=True)
    p_val.add_argument("--doc", default=None)
    p_val.add_argument("--require-implementable", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_pkg = sub.add_parser("package", help="package final bundle")
    p_pkg.add_argument("--feature-id", required=True)
    p_pkg.add_argument("--allow-gt-1600", default="no")
    p_pkg.set_defaults(func=cmd_package)

    p_inf = sub.add_parser("info", help="print engine/app config and paths")
    p_inf.set_defaults(func=cmd_info)
    
    p_wiz = sub.add_parser("wizard", help="interactive Q&A to create a feature")
    p_wiz.set_defaults(func=cmd_wizard)
    return p


def _prompt(prompt: str, default: str = None, validate=None) -> str:
    while True:
        if default:
            val = input(f"{prompt} [{default}]: ").strip()
            val = val if val else default
        else:
            val = input(f"{prompt}: ").strip()
        if validate and not validate(val):
            print("Invalid value; please try again.")
            continue
        return val


def _is_kebab_case(s: str) -> bool:
    return bool(re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", s))


def cmd_wizard(_args) -> int:
    engine_root = _engine_root()
    app_root = _app_root()
    cfg = _load_config(app_root)

    print("== Feature Wizard ==")
    fid = _prompt("Feature ID (kebab-case)", validate=_is_kebab_case)
    ns_default = cfg["project"].get("namespace", "")
    ns = _prompt("Namespace", default=ns_default)
    ver = _prompt("Version", default="0.1.0")
    today = _dt.date.today().isoformat()
    upd = _prompt("Updated date (YYYY-MM-DD)", default=today)
    tmpl_default = "templates/feature-capsule/feature-template"
    tmpl = _prompt("Template path (relative to engine root)", default=tmpl_default)

    template_dir = (engine_root / tmpl).resolve()
    if not template_dir.is_dir():
        print(f"ERROR: template not found: {template_dir}", file=sys.stderr)
        return 2

    dest_capsule = (app_root / cfg["paths"]["capsule"] / fid).resolve()
    dest_features = (app_root / cfg["paths"]["features"] / fid).resolve()

    print("\n== Summary ==")
    print(f"Feature ID: {fid}")
    print(f"Namespace:  {ns}")
    print(f"Version:    {ver}")
    print(f"Updated:    {upd}")
    print(f"Template:   {template_dir}")
    print("Destinations:")
    print(f"  capsule:  {dest_capsule}")
    print(f"  features: {dest_features}")

    dry = _prompt("Dry-run? (yes/no)", default="no", validate=lambda x: x.lower() in {"yes", "no"}).lower() == "yes"
    force = _prompt("Force overwrite if exists? (yes/no)", default="no", validate=lambda x: x.lower() in {"yes", "no"}).lower() == "yes"

    proceed = _prompt("Proceed? (yes/no)", default="yes", validate=lambda x: x.lower() in {"yes", "no"}).lower() == "yes"
    if not proceed:
        print("Aborted.")
        return 1

    if dry:
        print("DRY-RUN: would render, validate, and copy to destinations")
        return 0

    tmp_src = _render_template(template_dir, fid, ns, ver, upd)
    rc = _gated_copy_and_validate(tmp_src, fid, dest_capsule, dest_features, force=force, require_implementable=False)
    return rc


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
