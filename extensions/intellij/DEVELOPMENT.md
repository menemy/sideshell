# IntelliJ Plugin Development Notes

## Build & Install

```bash
# Build (requires JDK 17+, uses IntelliJ's bundled JDK 21)
cd extensions/intellij
JAVA_HOME="/Users/maksimnagaev/Applications/IntelliJ IDEA.app/Contents/jbr/Contents/Home" ./gradlew buildPlugin

# Install (ALWAYS quote paths — they contain spaces!)
PLUGIN_BASE="/Users/maksimnagaev/Library/Application Support/JetBrains/IntelliJIdea2025.3/plugins"
rm -rf "${PLUGIN_BASE}/sideshell-terminal"
ZIP_FILE="$(ls build/distributions/*.zip)"
unzip -q -o "$ZIP_FILE" -d "$PLUGIN_BASE"

# Then restart IntelliJ and click "Allow" in the consent dialog
```

## Architecture

### Terminal Types
IntelliJ 2025.3 has TWO terminal engines:
- **Classic**: `ShellTerminalWidget` (extends `JBTerminalWidget` from JediTerm)
- **Reworked** (new, default since 2025.2): Uses `EditorImpl` for rendering, managed by `TerminalToolWindowTabsManager`

### Split Pane Strategies

#### Classic Terminal Split
Use `JBTerminalWidgetListener.split(vertically)`:
```kotlin
val listener = widget.listener  // JBTerminalWidgetListener
if (listener != null && listener.canSplit(vertically)) {
    listener.split(vertically)  // true = vertical (side by side), false = horizontal (top/bottom)
}
```
This creates a real split pane within the terminal tab. The `TerminalSplitAction` class uses this internally.

#### New Terminal Split
For the **reworked terminal**, we create a new tracked tab via `createTab()` instead of using
`TW.SplitRight`, because `TW.SplitRight` creates tool window splits with async tab creation
that are NOT reliably detectable via `getTabs()` reflection.

**Why TW.SplitRight doesn't work**: It calls `TerminalToolWindowSplitContentProvider.createContentCopy()`
which uses `createTabBuilder().shouldAddToToolWindow(false).createTab()`. The tab creation involves
coroutines that complete asynchronously. While `addToTabsList()` IS called internally, the tab
may not appear in `getTabs()` when read from non-EDT threads due to coroutine scheduling.

For the **classic terminal**, use `JBTerminalWidgetListener.split(vertically)`:
```kotlin
val listener = widget.listener  // JBTerminalWidgetListener
if (listener != null && listener.canSplit(vertically)) {
    listener.split(vertically)  // true = vertical (side by side), false = horizontal (top/bottom)
}
```
This creates a real split pane within the terminal tab.

### Terminal Detection

Detection uses a cascade:
1. **New API**: `TerminalToolWindowTabsManager.getTabs()` via reflection
2. **Nested ContentManager scan**: Scan tool window component tree for nested `ContentManager` instances. For each untracked `Content`, find `ShellTerminalWidget` via `UIUtil.findComponentsOfType(content.component, ShellTerminalWidget.class)`.
3. **Classic ContentManager**: `toolWindow.contentManager.contents`
4. **UIUtil frame scan**: `UIUtil.findComponentsOfType(frame.rootPane, ShellTerminalWidget::class.java)`

**Key discovery**: Even the "reworked" terminal wraps a `ShellTerminalWidget` inside `TerminalToolWindowPanel → TerminalWrapperPanel → ShellTerminalWidget`. So UIUtil scanning for `ShellTerminalWidget` works for BOTH terminal engines.

### Key Classes
- `ShellTerminalWidget` → classic terminal widget, has `getListener()` → `JBTerminalWidgetListener`
- `JBTerminalWidgetListener` → has `split(boolean)`, `canSplit(boolean)`, `onSessionClosed()`
- `TerminalToolWindowTabsManager` → new API for managing terminal tabs (reflection)
- `TerminalToolWindowTab` → individual tab in new API
- `TerminalToolWindowSplitContentProvider` → creates content when TW splits terminal

### terminalTitle Parsing
`widget.terminalTitle` returns a complex object with format:
```
userDefined=null, application=null, tag=null, default=Local (2), trackTerminalApplicationTitle=null
```
Parse with: `Regex("default=(.+?)(?:,\\s|$)")`

## Security
- Token auth: 256-bit random token in `~/.sideshell/intellij-port` (0600 permissions)
- User consent dialog on first connection per IDE session
- Server binds to 127.0.0.1 only

## Port File
Location: `~/.sideshell/intellij-port`
```json
{"port":46118,"pid":12345,"token":"hex...","ide":"intellij","version":"0.1.0"}
```

## Logs
IntelliJ logs: `~/Library/Logs/JetBrains/IntelliJIdea2025.3/idea.log`
Filter: `grep "sideshell:" idea.log`
