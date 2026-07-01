# Publishing Guide

## TL;DR — Do You Need Stores?

**Not yet.** For early stage / internal use, self-install is simpler:

```bash
make install          # installs everything locally
make package          # creates distributable .whl, .vsix, .zip files
```

Share the artifacts directly (GitHub Releases, internal Slack, etc.).

**Publish to stores when:**
- You want discoverability (users can search "sideshell" in marketplace)
- You want auto-updates (stores handle version bumps)
- You have stable API / no breaking changes between releases
- You want trust signals (verified publisher badge)

---

## 1. PyPI (Python MCP Server)

### Recommended: Trusted Publishing (no tokens)

The repo ships `.github/workflows/publish.yml`, which publishes via PyPI
Trusted Publishing (OIDC) — nothing secret is stored. One-time setup:

1. Create an account at https://pypi.org and **enable 2FA** (now mandatory).
2. Go to **Account → Publishing → Add a pending publisher** and enter:
   - PyPI project name: `sideshell-mcp`
   - Owner: `menemy` · Repository: `sideshell`
   - Workflow name: `publish.yml` · Environment: `pypi`
3. (Optional) In the GitHub repo, create an Environment named `pypi`
   (Settings → Environments) to gate releases.
4. Cut a release: bump `version` in `pyproject.toml`, then publish a
   **GitHub Release** (tag `vX.Y.Z`). The workflow builds, `twine check`s, and
   uploads automatically.

After that, `pip install sideshell-mcp` / `uvx sideshell-mcp` just work.

### Alternative: API token (manual)

```bash
pip install build twine
```

Create account at https://pypi.org and generate API token.

```bash
# ~/.pypirc
[pypi]
username = __token__
password = pypi-AgEI...    # your token
```

### Publish

```bash
make publish-python
# or manually:
python -m build
twine upload dist/*
```

### After publishing

Users install with:
```bash
pip install sideshell-mcp
# or
uvx sideshell-mcp
```

### Best practices
- Bump version in `pyproject.toml` before each release
- Use semver: breaking changes = major, features = minor, fixes = patch
- Test with `twine upload --repository testpypi dist/*` first
- Add GitHub Actions workflow for automated publishing on tag

---

## 2. VSCode Marketplace

### Setup (one-time)

1. Create Azure DevOps org at https://dev.azure.com
2. Create Personal Access Token (PAT) with "Marketplace > Manage" scope
3. Create publisher at https://marketplace.visualstudio.com/manage

```bash
cd extensions/vscode
npx @vscode/vsce login sideshell    # enter your PAT
```

### Publish

```bash
make publish-vscode
# or manually:
cd extensions/vscode
npx @vscode/vsce publish
```

### After publishing

Users install with:
- VSCode: Extensions panel → search "sideshell"
- CLI: `code --install-extension sideshell.sideshell-terminal`

### Open VSX (alternative — for Cursor, VSCodium, etc.)

Cursor and VSCodium don't use Microsoft's marketplace. They use Open VSX:

```bash
npm install -g ovsx
ovsx create-namespace sideshell    # one-time
ovsx publish sideshell-terminal-*.vsix -p $OVSX_TOKEN
```

Register at https://open-vsx.org

### Best practices
- Bump version in `package.json` AND `bridge.ts` (port file version)
- Include a good icon (128x128 PNG) and `README.md` in the extension
- Add `CHANGELOG.md` in extension dir — marketplace shows it
- Pre-release channel: `vsce publish --pre-release` for beta versions
- Cursor users: consider publishing to Open VSX too, or provide .vsix downloads

---

## 3. JetBrains Marketplace

### Setup (one-time)

1. Create account at https://plugins.jetbrains.com
2. Get permanent token: Hub Profile → Authentication → Generate Token

### Publish

**Web upload (simplest):**
1. Go to https://plugins.jetbrains.com/plugin/add#step=upload
2. Upload the .zip from `extensions/intellij/build/distributions/`
3. Fill in plugin details, submit for review

**CLI upload:**
```bash
curl -i \
  --header "Authorization: Bearer $HUB_TOKEN" \
  -F pluginId=com.sideshell.terminal \
  -F file=@extensions/intellij/build/distributions/sideshell-terminal-0.1.0.zip \
  https://plugins.jetbrains.com/plugin/uploadNewVersion
```

**Gradle (automated):**
Add to `build.gradle.kts`:
```kotlin
intellijPlatform {
    publishing {
        token = providers.environmentVariable("JETBRAINS_TOKEN")
    }
}
```
Then: `./gradlew publishPlugin`

### After publishing

Users install with:
- Settings → Plugins → Marketplace → search "sideshell"

### Best practices
- JetBrains reviews every submission (takes 1-3 business days)
- Bump version in `build.gradle.kts`
- `sinceBuild` / `untilBuild` — keep narrow at first (single major version)
- Provide plugin icon (40x40 SVG in `src/main/resources/META-INF/pluginIcon.svg`)
- Sign the plugin for verified badge: `./gradlew signPlugin`

---

## 4. GitHub Releases (Recommended as First Step)

Before marketplace publishing, use GitHub Releases for distribution:

```bash
# Build all artifacts
make package

# Tag and release
git tag v0.2.0
git push origin v0.2.0

# Create release via gh CLI
gh release create v0.2.0 \
  dist/sideshell_mcp-*.whl \
  extensions/vscode/sideshell-terminal-*.vsix \
  extensions/intellij/build/distributions/*.zip \
  --title "v0.2.0" \
  --notes "Release notes here"
```

Users install from release:
```bash
# Python
pip install https://github.com/.../sideshell_mcp-1.0.0-py3-none-any.whl

# VSCode
code --install-extension sideshell-terminal-0.2.0.vsix

# IntelliJ — download .zip, install from disk in IDE
```

### Advantages over stores
- No review process, instant publishing
- Full control over distribution
- Can include pre-release / nightly builds
- Single place for all 3 artifacts

### Disadvantages
- No auto-updates
- No discoverability (users must know the repo)
- No verified publisher badge

---

## Versioning Strategy

Keep versions in sync across components:

| Component | Version location | Current |
|-----------|-----------------|---------|
| Python | `pyproject.toml` → `version` | 1.0.0 |
| VSCode | `extensions/vscode/package.json` → `version` | 1.0.0 |
| VSCode | `extensions/vscode/src/bridge.ts` → `version` (port file) | 1.0.0 |
| IntelliJ | `extensions/intellij/build.gradle.kts` → `version` | 1.0.0 |
| IntelliJ | `SideshellBridgeService.kt` → `version` (port file) | 1.0.0 |

Suggested flow:
1. Bump versions in all files
2. `make package` — build all artifacts
3. `make test` — verify
4. Commit, tag: `git tag v0.2.0`
5. Publish: `make publish` or GitHub Release

---

## CI/CD Automation

Add to `.github/workflows/release.yml`:

```yaml
on:
  push:
    tags: ['v*']

jobs:
  publish-pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install build twine
      - run: python -m build
      - run: twine upload dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}

  publish-vscode:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: cd extensions/vscode && npm install && npx @vscode/vsce publish
        env:
          VSCE_PAT: ${{ secrets.VSCE_PAT }}

  publish-intellij:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: { java-version: '21' }
      - run: cd extensions/intellij && ./gradlew publishPlugin
        env:
          JETBRAINS_TOKEN: ${{ secrets.JETBRAINS_TOKEN }}
```
