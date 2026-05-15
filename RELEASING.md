# Release Guide（发行手册）

本文覆盖：GitHub 发布、PyPI 上传、项目主页同步（GitHub Pages）和全量发布脚本。

## 0. 预检

```bash
python -m unittest discover -s tests
python -m compileall literature_agent
python -m build
python -m twine check dist/*
```

## 1. 统一版本号

版本信息应保持一致：
- `pyproject.toml`
- `literature_agent/__init__.py`
- `literature_agent/utils.py`（User-Agent）
- `literature_agent/workflow.py`（manifest 标记）
- `CHANGELOG.md`

## 2. 本地预发布（Dry-run）

```bash
./publish_pypi.sh --dry-run --version <VERSION>
```

或直接执行：

```bash
./scripts/release_everywhere.sh --dry-run
```

## 3. 一键发布

### A. 推荐流程（包含 GitHub + PyPI）

```bash
# 先在 shell 中配置 PyPI token
export PYPI_TOKEN='pypi-...'

# 执行整条链路（预检、提版本、提交打tag、推仓库、建Release、上传PyPI）
./scripts/release_everywhere.sh --version <VERSION>
```

### B. 只发 GitHub / 不发 PyPI

```bash
./scripts/release_everywhere.sh --version <VERSION> --no-pypi
```

### C. 仅生成本地发布产物（无推送）

```bash
./scripts/release_everywhere.sh --version <VERSION> --skip-push --no-pypi
```

## 4. GitHub Pages（主页）

主页内容在 `docs/`。建议：

1. 仓库 Settings → Pages
2. Build and deployment → Source：`Deploy from a branch`
3. Branch：`main`
4. Folder：`/docs`

也可走 workflow：推送 `main` 后会自动触发 `.github/workflows/gh-pages.yml` 部署。

## 5. 发布后核对

- GitHub Release 页面包含该版本的 release notes（脚本默认从 `CHANGELOG.md` 最新条目生成）
- PyPI 页面版本号与发布版本一致
- `README` 与 `README.zh-CN.md` 中示例命令和版本号保持一致
- 主页链接和徽章在发布版本后可访问
