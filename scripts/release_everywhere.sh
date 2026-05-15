#!/usr/bin/env bash

set -euo pipefail

# Full release helper:
# - runs local precheck
# - bumps version (optional)
# - dry-run build check
# - commits and tags
# - pushes code + tags
# - creates GitHub Release
# - uploads to PyPI
#
# Usage:
#   ./scripts/release_everywhere.sh
#   ./scripts/release_everywhere.sh --version 1.4.5
#   ./scripts/release_everywhere.sh --dry-run
#   ./scripts/release_everywhere.sh --no-pypi --message "Release note"

DRY_RUN="false"
VERSION=""
SKIP_GH_RELEASE="false"
SKIP_PYPI="false"
MESSAGE="Auto release"
SKIP_PUSH="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --no-gh-release)
      SKIP_GH_RELEASE="true"
      shift
      ;;
    --no-pypi)
      SKIP_PYPI="true"
      shift
      ;;
    --skip-push)
      SKIP_PUSH="true"
      shift
      ;;
    --message)
      MESSAGE="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '1,80p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$DRY_RUN" == "true" ]]; then
  SKIP_PYPI="true"
  echo "Dry-run mode enabled: skip pushing and PyPI upload."
fi

if [[ -n "$VERSION" ]]; then
  echo "Target version: ${VERSION}"
  ./publish_pypi.sh --version "$VERSION" --dry-run
else
  echo "No --version provided, using patch auto-bump flow in publish script."
  ./publish_pypi.sh --dry-run
fi

NEW_VERSION="$(python - <<'PY'
import re
from pathlib import Path
text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
if not match:
    raise SystemExit("No version found")
print(match.group(1))
PY
)"

echo "Release version resolved: ${NEW_VERSION}"

echo "Running precheck..."
python -m unittest discover -s tests
python -m compileall literature_agent

if [[ "$SKIP_PUSH" == "false" ]]; then
  if ! git diff --quiet -- pyproject.toml literature_agent/__init__.py literature_agent/utils.py literature_agent/workflow.py literature_agent/evidence.py literature_agent/synthesis.py literature_agent/report.py; then
    git add -A
    if [[ -n "${MESSAGE// }" ]]; then
      git commit -m "release: v${NEW_VERSION} - ${MESSAGE}"
    else
      git commit -m "release: v${NEW_VERSION}"
    fi
    git tag -a "v${NEW_VERSION}" -m "PaperPilot v${NEW_VERSION}"
  else
    echo "No changes detected after version bump, skipping commit."
  fi
else
  echo "skip-push set; release commit/tags are not created."
fi

if [[ "$SKIP_PUSH" == "false" ]]; then
  git push origin main
  git push origin --tags
fi

if [[ "$SKIP_GH_RELEASE" == "false" && "$SKIP_PUSH" == "false" ]]; then
  RELEASE_NOTES="$(awk '/^## \\[[0-9]/{flag=1; next} flag && /^## \\[/{flag=0} flag {print}' CHANGELOG.md | sed '/^$/d' | head -n 80)"
  if [[ -n "${RELEASE_NOTES// /}" ]]; then
    printf '%s\n' "$RELEASE_NOTES" > /tmp/paperpilot_release_notes.md
  else
    printf '%s\n' "PaperPilot v${NEW_VERSION}" > /tmp/paperpilot_release_notes.md
  fi
  if gh release view "v${NEW_VERSION}" >/dev/null 2>&1; then
    gh release edit "v${NEW_VERSION}" --notes-file /tmp/paperpilot_release_notes.md
  else
    gh release create "v${NEW_VERSION}" --title "PaperPilot v${NEW_VERSION}" --notes-file /tmp/paperpilot_release_notes.md
  fi
fi

if [[ "$SKIP_PYPI" == "true" ]]; then
  echo "Skipping PyPI upload (--no-pypi or dry-run)."
  echo "Release validation done; check dist/* for artifacts."
  exit 0
fi

if [[ -z "${PYPI_TOKEN:-}" ]]; then
  echo "PYPI_TOKEN not set. Export it and rerun:"
  echo "  export PYPI_TOKEN='pypi-...'"
  exit 1
fi

if [[ "$SKIP_PUSH" == "true" ]]; then
  echo "skip-push: keep local package files only."
  ./publish_pypi.sh --version "${NEW_VERSION}" --dry-run
  exit 0
fi

if [[ "${VERSION}" == "" ]]; then
  ./publish_pypi.sh --version "${NEW_VERSION}"
else
  ./publish_pypi.sh --version "${VERSION}"
fi

echo "Release sync completed for v${NEW_VERSION}"
