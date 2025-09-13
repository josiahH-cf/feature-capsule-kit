Capsule Engine
===============

This engine provides a reusable template and a single Python entrypoint to create, validate, and package feature capsules.

Key paths
- Template: `templates/feature-capsule/feature-template/`
- Validators: `capsule/reports/validation/validate_all.sh`
- Packager: `tools/final_bundle/verify_and_package.sh`

CLI (entrypoint.py)
- Wizard: `python3 tools/capsule-engine/entrypoint.py wizard` (interactive Q&A)
- New: `python3 tools/capsule-engine/entrypoint.py new --feature-id my-feature [--from-template <path>] [--version 0.1.0] [--date YYYY-MM-DD] [--dry-run] [--force]`
- Validate: `python3 tools/capsule-engine/entrypoint.py validate --feature-id my-feature [--doc <path>] [--require-implementable]`
- Package: `python3 tools/capsule-engine/entrypoint.py package --feature-id my-feature [--allow-gt-1600 yes|no]`
- Info: `python3 tools/capsule-engine/entrypoint.py info`

Do not place app-specific feature instances inside the engine. All app state lives under the app repo (e.g., `automatr-capsule/`).
