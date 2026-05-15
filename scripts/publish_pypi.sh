#!/usr/bin/env bash
set -euo pipefail

# PaperPilot PyPI release helper.
#
# Usage:
#   ./scripts/publish_pypi.sh                 # auto bump patch, build, upload to PyPI
#   ./scripts/publish_pypi.sh --version 1.0.2  # set an exact version
#   ./scripts/publish_pypi.sh --dry-run        # bump/build/check, but do not upload
#   ./scripts/publish_pypi.sh --testpypi       # upload to TestPyPI
#
# Token options:
#   1. Safer: export PYPI_TOKEN="pypi-..."
#   2. Simpler: paste the token below.

PYPI_TOKEN="${PYPI_TOKEN:-}"
# PYPI_TOKEN="pypi-PASTE_YOUR_TOKEN_HERE"

PACKAGE_NAME="paperpilot"
TARGET_VERSION=""
DRY_RUN="false"
REPOSITORY="pypi"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      TARGET_VERSION="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --testpypi)
      REPOSITORY="testpypi"
      shift
      ;;
    -h|--help)
      sed -n '1,28p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

python - <<'PY' "$TARGET_VERSION"
import re
import sys
from pathlib import Path

target = sys.argv[1].strip()
pyproject = Path("pyproject.toml")
text = pyproject.read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.M)
if not match:
    raise SystemExit("Could not find project version in pyproject.toml")

if target:
    if not re.fullmatch(r"\d+\.\d+\.\d+", target):
        raise SystemExit("--version must look like 1.2.3")
    new_version = target
else:
    major, minor, patch = map(int, match.groups())
    new_version = f"{major}.{minor}.{patch + 1}"

old_version = match.group(0).split('"')[1]
replacements = {
    "pyproject.toml": (
        (rf'version = "{re.escape(old_version)}"', f'version = "{new_version}"'),
    ),
    "literature_agent/__init__.py": (
        (rf'__version__ = "{re.escape(old_version)}"', f'__version__ = "{new_version}"'),
    ),
    "literature_agent/utils.py": (
        (rf'paperpilot/{re.escape(old_version)}', f'paperpilot/{new_version}'),
    ),
    "literature_agent/workflow.py": (
        (rf'"paperpilot_version": "{re.escape(old_version)}"', f'"paperpilot_version": "{new_version}"'),
    ),
    "使用文档.md": (
        (rf'paperpilot-{re.escape(old_version)}-py3-none-any\.whl', f'paperpilot-{new_version}-py3-none-any.whl'),
    ),
}

for filename, rules in replacements.items():
    path = Path(filename)
    if not path.exists():
        continue
    data = path.read_text(encoding="utf-8")
    for pattern, repl in rules:
        data = re.sub(pattern, repl, data)
    path.write_text(data, encoding="utf-8")

print(new_version)
PY

NEW_VERSION="$(python - <<'PY'
import re
from pathlib import Path
text = Path("pyproject.toml").read_text(encoding="utf-8")
print(re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1))
PY
)"

echo "Releasing ${PACKAGE_NAME} ${NEW_VERSION}"

rm -rf build dist "${PACKAGE_NAME}.egg-info" paperpilot.egg-info

python -m pip install --upgrade build twine
python -m unittest discover -s tests
python -m compileall literature_agent
python -m build
python -m twine check "dist/${PACKAGE_NAME}-${NEW_VERSION}"*

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Dry run complete. Built files:"
  ls -1 dist
  exit 0
fi

if [[ -z "${PYPI_TOKEN}" || "${PYPI_TOKEN}" == "pypi-PASTE_YOUR_TOKEN_HERE" ]]; then
  echo "Missing PyPI token. Set PYPI_TOKEN or paste it near the top of this script." >&2
  exit 1
fi

if [[ "${REPOSITORY}" == "testpypi" ]]; then
  python -m twine upload --repository testpypi -u __token__ -p "${PYPI_TOKEN}" "dist/${PACKAGE_NAME}-${NEW_VERSION}"*
else
  python -m twine upload -u __token__ -p "${PYPI_TOKEN}" "dist/${PACKAGE_NAME}-${NEW_VERSION}"*
fi

echo "Uploaded ${PACKAGE_NAME} ${NEW_VERSION} to ${REPOSITORY}."
echo "Verify with:"
echo "  python -m pip install --upgrade ${PACKAGE_NAME} -i https://pypi.org/simple"
echo "  python -c 'import literature_agent; print(literature_agent.__version__)'"
