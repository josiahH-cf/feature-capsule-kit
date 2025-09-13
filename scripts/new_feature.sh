#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: tools/capsule-engine/scripts/new_feature.sh FEATURE_ID [--from-template <path>] [--dry-run yes|no] [--force]

Creates a new feature capsule by rendering the engine template with placeholders.

Inputs:
  FEATURE_ID             Required feature identifier (kebab-case)
Options:
  --from-template <path> Path relative to engine root (default: templates/feature-capsule/feature-template)
  --dry-run yes|no       Print actions without writing (default: no)
  --force                Overwrite destinations if they exist (default: disabled)

Environment overrides:
  VERSION                Default 0.1.0
  UPDATED_DATE           Default today (YYYY-MM-DD)
USAGE
}

FEATURE_ID="${1:-}"
TEMPLATE_REL="templates/feature-capsule/feature-template"
DRY_RUN="no"
FORCE="no"

shift $(( $# > 0 ? 1 : 0 )) || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-template)
      TEMPLATE_REL="$2"; shift 2;;
    --dry-run)
      DRY_RUN="$2"; shift 2;;
    --force)
      FORCE="yes"; shift 1;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unexpected argument: $1" >&2; usage; exit 2;;
  esac
done

if [[ -z "${FEATURE_ID:-}" ]]; then
  echo "ERROR: FEATURE_ID is required" >&2; usage; exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENGINE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_ROOT="$(cd "$ENGINE_ROOT/../.." && pwd)"
CONFIG="$APP_ROOT/capsule.project.toml"

if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: Config not found: $CONFIG" >&2
  exit 2
fi

parse_toml_key() {
  local section="$1" key="$2"
  awk -v sec="[$section]" -v key="$key" '
    BEGIN{insec=0}
    $0 ~ /^\s*\[[^\]]+\]\s*$/ {insec=($0==sec); next}
    insec==1 {
      # match key = "value"
      if ($0 ~ ("^\\s*" key "\\s*=\\s*")) {
        val=$0
        sub(/^[^=]*=\s*/, "", val)
        gsub(/^"|"\s*$/, "", val)
        gsub(/^[ \t]+|[ \t]+$/, "", val)
        gsub(/\r/, "", val)
        print val; exit
      }
    }
  ' "$CONFIG"
}

NAMESPACE="$(parse_toml_key project namespace)"
PATH_FEATURES="$(parse_toml_key paths features)"
PATH_CAPSULE="$(parse_toml_key paths capsule)"
PATH_FINAL_DOCS="$(parse_toml_key paths final_docs)"
PATH_PLANNING="$(parse_toml_key paths planning)"

if [[ -z "$NAMESPACE" || -z "$PATH_FEATURES" || -z "$PATH_CAPSULE" ]]; then
  echo "ERROR: Missing required keys in $CONFIG" >&2
  exit 2
fi

VERSION="${VERSION:-0.1.0}"
UPDATED_DATE="${UPDATED_DATE:-$(date +%F)}"

TEMPLATE_ABS="$ENGINE_ROOT/$TEMPLATE_REL"
if [[ ! -d "$TEMPLATE_ABS" ]]; then
  echo "ERROR: Template not found: $TEMPLATE_ABS" >&2
  exit 2
fi

DEST_CAPSULE="$APP_ROOT/$PATH_CAPSULE/$FEATURE_ID"
DEST_FEATURES="$APP_ROOT/$PATH_FEATURES/$FEATURE_ID"

echo "== New Feature =="
echo "Feature ID: $FEATURE_ID"
echo "Template:   $TEMPLATE_ABS"
echo "Namespace:  $NAMESPACE"
echo "Dest(caps): $DEST_CAPSULE"
echo "Dest(feat): $DEST_FEATURES"

if [[ "$DRY_RUN" == "yes" ]]; then
  echo "DRY-RUN: would render template and copy to destinations"
  exit 0
fi

if [[ -e "$DEST_CAPSULE" || -e "$DEST_FEATURES" ]]; then
  if [[ "$FORCE" != "yes" ]]; then
    echo "ERROR: Destination exists. Use --force to overwrite." >&2
    exit 2
  fi
fi

TMPDIR="$(mktemp -d -t feature-${FEATURE_ID}-XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT
cp -R "$TEMPLATE_ABS" "$TMPDIR/src"

# Replace placeholders in file contents
find "$TMPDIR/src" -type f -print0 | xargs -0 sed -i \
  -e "s/{{FEATURE_ID}}/$FEATURE_ID/g" \
  -e "s/{{PROJECT_NAMESPACE}}/$NAMESPACE/g" \
  -e "s/{{VERSION}}/$VERSION/g" \
  -e "s/{{UPDATED_DATE}}/$UPDATED_DATE/g"

# Rename any path elements containing {{FEATURE_ID}}
while IFS= read -r -d '' P; do
  NEWP="${P//\{\{FEATURE_ID\}\}/$FEATURE_ID}"
  if [[ "$NEWP" != "$P" ]]; then
    mkdir -p "$(dirname "$NEWP")"
    mv "$P" "$NEWP"
  fi
done < <(find "$TMPDIR/src" -depth -name '*{{FEATURE_ID}}*' -print0)

# Copy capsule subtree
if [[ -d "$TMPDIR/src/capsule/$FEATURE_ID" ]]; then
  mkdir -p "$DEST_CAPSULE"
  if [[ "$FORCE" == "yes" && -e "$DEST_CAPSULE" ]]; then rm -rf "$DEST_CAPSULE"; fi
  cp -R "$TMPDIR/src/capsule/$FEATURE_ID" "$DEST_CAPSULE/.."
fi

# Copy features subtree
if [[ -d "$TMPDIR/src/features/$FEATURE_ID" ]]; then
  mkdir -p "$DEST_FEATURES"
  if [[ "$FORCE" == "yes" && -e "$DEST_FEATURES" ]]; then rm -rf "$DEST_FEATURES"; fi
  cp -R "$TMPDIR/src/features/$FEATURE_ID" "$DEST_FEATURES/.."
fi

# Run validators
echo "== Running validators =="
FEATURE_ID="$FEATURE_ID" bash "$ENGINE_ROOT/capsule/reports/validation/validate_all.sh" || VALID_RC=$?
VALID_RC=${VALID_RC:-0}

echo "== Summary =="
echo "Capsule path: $DEST_CAPSULE"
echo "Features path: $DEST_FEATURES"
if [[ $VALID_RC -ne 0 ]]; then
  echo "Validation: FAIL (exit $VALID_RC)"; exit $VALID_RC
else
  echo "Validation: PASS"
fi

exit 0
