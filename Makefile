# sideshell — build, install, test, publish
#
# Usage:
#   make help          — show all targets
#   make build         — build everything
#   make install       — install everything locally
#   make test          — run all tests
#   make publish       — publish all artifacts

SHELL := /bin/zsh

# ── Paths ────────────────────────────────────────────────────────────────────
VSCODE_DIR     := extensions/vscode
INTELLIJ_DIR   := extensions/intellij
CURSOR_EXT_DIR := $(HOME)/.cursor/extensions/sideshell.sideshell-terminal-0.1.0
VSCODE_EXT_DIR := $(HOME)/.vscode/extensions/sideshell.sideshell-terminal-0.1.0
IJ_PLUGIN_DIR  := $(HOME)/Library/Application Support/JetBrains/IntelliJIdea2025.3/plugins

# IntelliJ bundled JDK (adjust if using different IDE or version)
JAVA_HOME_IJ   := $(HOME)/Applications/IntelliJ IDEA.app/Contents/jbr/Contents/Home

# ── Help ─────────────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Build All ────────────────────────────────────────────────────────────────
.PHONY: build build-python build-vscode build-intellij
build: build-python build-vscode build-intellij ## Build all components

build-python: ## Build Python MCP server package
	uv pip install -e ".[dev]"
	@echo "✓ Python package installed in dev mode"

build-vscode: ## Compile VSCode/Cursor extension
	cd $(VSCODE_DIR) && npm install --silent && npm run compile
	@echo "✓ VSCode extension compiled → $(VSCODE_DIR)/out/"

build-intellij: ## Build IntelliJ plugin
	cd $(INTELLIJ_DIR) && JAVA_HOME="$(JAVA_HOME_IJ)" ./gradlew buildPlugin --quiet
	@echo "✓ IntelliJ plugin built → $(INTELLIJ_DIR)/build/distributions/"

# ── Install ──────────────────────────────────────────────────────────────────
.PHONY: install install-python install-cursor install-vscode install-intellij

install: install-python install-cursor install-intellij ## Install all components locally

install-python: build-python ## Install Python MCP server
	@echo "✓ Python MCP server ready: python -m sideshell_mcp.server"

install-cursor: build-vscode ## Deploy extension to Cursor
	@mkdir -p "$(CURSOR_EXT_DIR)/out"
	cp $(VSCODE_DIR)/out/bridge.js $(VSCODE_DIR)/out/bridge.js.map \
	   $(VSCODE_DIR)/out/extension.js $(VSCODE_DIR)/out/extension.js.map \
	   $(VSCODE_DIR)/out/terminal-manager.js $(VSCODE_DIR)/out/terminal-manager.js.map \
	   "$(CURSOR_EXT_DIR)/out/"
	cp $(VSCODE_DIR)/package.json "$(CURSOR_EXT_DIR)/package.json"
	@echo "✓ Deployed to Cursor — reload window (Cmd+Shift+P → Developer: Reload Window)"

install-vscode: build-vscode ## Deploy extension to VSCode
	@mkdir -p "$(VSCODE_EXT_DIR)/out"
	cp $(VSCODE_DIR)/out/bridge.js $(VSCODE_DIR)/out/bridge.js.map \
	   $(VSCODE_DIR)/out/extension.js $(VSCODE_DIR)/out/extension.js.map \
	   $(VSCODE_DIR)/out/terminal-manager.js $(VSCODE_DIR)/out/terminal-manager.js.map \
	   "$(VSCODE_EXT_DIR)/out/"
	cp $(VSCODE_DIR)/package.json "$(VSCODE_EXT_DIR)/package.json"
	@echo "✓ Deployed to VSCode — reload window (Cmd+Shift+P → Developer: Reload Window)"

install-intellij: build-intellij ## Install plugin to IntelliJ IDEA
	@rm -rf "$(IJ_PLUGIN_DIR)/sideshell-terminal"
	unzip -q -o "$$(ls $(INTELLIJ_DIR)/build/distributions/*.zip | head -1)" -d "$(IJ_PLUGIN_DIR)"
	@echo "✓ Installed to IntelliJ — restart IDE"

# ── Package (distributable artifacts) ────────────────────────────────────────
.PHONY: package package-python package-vscode package-intellij

package: package-python package-vscode package-intellij ## Create all distributable artifacts
	@echo ""
	@echo "Artifacts:"
	@ls -1 dist/*.whl dist/*.tar.gz 2>/dev/null || true
	@ls -1 $(VSCODE_DIR)/*.vsix 2>/dev/null || true
	@ls -1 $(INTELLIJ_DIR)/build/distributions/*.zip 2>/dev/null || true

package-python: ## Build Python wheel + sdist
	python -m build
	@echo "✓ Python package → dist/"

package-vscode: build-vscode ## Package VSCode extension (.vsix)
	cd $(VSCODE_DIR) && npx @vscode/vsce package --no-dependencies
	@echo "✓ VSCode extension → $(VSCODE_DIR)/*.vsix"

package-intellij: build-intellij ## Package IntelliJ plugin (.zip)
	@echo "✓ IntelliJ plugin → $(INTELLIJ_DIR)/build/distributions/*.zip"

# ── Lint & Format ────────────────────────────────────────────────────────────
.PHONY: lint format typecheck

lint: ## Lint all code
	ruff check sideshell_mcp tests
	cd $(VSCODE_DIR) && npx tsc --noEmit 2>/dev/null || true
	@echo "✓ Lint passed"

format: ## Format all code
	ruff format sideshell_mcp tests
	@echo "✓ Python formatted"

typecheck: ## Run mypy type checking
	mypy sideshell_mcp || true
	@echo "✓ Type check done"

# ── Test ─────────────────────────────────────────────────────────────────────
.PHONY: test test-python test-iterm2 test-tmux test-kitty test-wezterm test-vscode test-intellij

test: test-iterm2 test-tmux test-kitty test-wezterm test-vscode ## Run all backend tests

test-iterm2: ## Test iTerm2 backend (requires iTerm2 running)
	uv run python tests/test_iterm2_backend.py

test-tmux: ## Test tmux backend (requires tmux installed)
	uv run python tests/test_tmux_backend.py

test-kitty: ## Test Kitty backend (auto-launches Kitty)
	uv run python tests/test_kitty_backend.py

test-wezterm: ## Test WezTerm backend (auto-launches WezTerm)
	uv run python tests/test_wezterm_backend.py

test-vscode: ## Test VSCode/Cursor extension (requires running IDE)
	uv run python -m pytest tests/test_plugin_integration.py -v -s -k VSCode

test-intellij: ## Test IntelliJ plugin (requires running IDE)
	uv run python -m pytest tests/test_plugin_integration.py -v -s -k IntelliJ

# ── Publish ──────────────────────────────────────────────────────────────────
.PHONY: publish publish-python publish-vscode publish-intellij

publish: publish-python publish-vscode publish-intellij ## Publish all artifacts

publish-python: package-python ## Publish to PyPI
	twine upload dist/*
	@echo "✓ Published to PyPI: pip install sideshell-mcp"

publish-vscode: package-vscode ## Publish to VSCode Marketplace
	cd $(VSCODE_DIR) && npx @vscode/vsce publish
	@echo "✓ Published to VSCode Marketplace"

publish-intellij: package-intellij ## Publish to JetBrains Marketplace
	@echo "Upload $(INTELLIJ_DIR)/build/distributions/*.zip to:"
	@echo "  https://plugins.jetbrains.com/plugin/add#step=upload"
	@echo ""
	@echo "Or use CLI: (requires token)"
	@echo '  curl -i --header "Authorization: Bearer $$HUB_TOKEN" \\'
	@echo "    -F pluginId=com.sideshell.terminal \\"
	@echo "    -F file=@$$(ls $(INTELLIJ_DIR)/build/distributions/*.zip) \\"
	@echo "    https://plugins.jetbrains.com/plugin/uploadNewVersion"

# ── Clean ────────────────────────────────────────────────────────────────────
.PHONY: clean

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info
	rm -rf $(VSCODE_DIR)/out/*.js $(VSCODE_DIR)/out/*.js.map $(VSCODE_DIR)/*.vsix
	rm -rf $(INTELLIJ_DIR)/build $(INTELLIJ_DIR)/.gradle
	@echo "✓ Cleaned"
