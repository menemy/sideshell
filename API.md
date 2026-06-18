# API Reference

Complete reference for all 17 tools provided by **sideshell**.

## Table of Contents

- [Command Execution](#command-execution)
  - [execute](#execute)
  - [control-char](#control-char)
  - [paste](#paste)
  - [clear](#clear)
- [Terminal Reading](#terminal-reading)
  - [read](#read)
- [Session Management](#session-management)
  - [list](#list)
  - [focus](#focus)
  - [close-session](#close-session)
  - [get-terminal-state](#get-terminal-state)
- [Session Creation](#session-creation)
  - [new-window](#new-window)
  - [new-tab](#new-tab)
  - [new-session](#new-session)
  - [split](#split)
- [Appearance](#appearance)
  - [set-appearance](#set-appearance)
  - [set-color-preset](#set-color-preset)
  - [list-color-presets](#list-color-presets)
- [Alerts](#alerts)
  - [show-alert](#show-alert)

---

## Command Execution

### execute

Execute a command in a terminal session. Supports fire-and-forget, waiting for completion, and broadcasting to multiple sessions.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `command` | string | No | - | Command to execute. If omitted with `wait=true`, monitors session without executing |
| `session_id` | string | No | current | Target session ID |
| `targets` | array[string] | No | - | Multiple session IDs for broadcast (overrides `session_id`) |
| `wait` | boolean | No | `false` | Wait for command completion |
| `timeout` | integer | No | `30` | Max seconds to wait (when `wait=true`) |
| `watch_for` | string | No | `"prompt"` | What to wait for: `"prompt"` (shell ready), `"output"` (any change), `"silence"` (2s stability) |
| `return_focus` | boolean | No | `true` | Return focus to Claude after execution |

**Examples:**

```json
// Fire and forget
{"command": "npm install"}

// Wait for completion
{"command": "npm test", "wait": true, "timeout": 60}

// Broadcast to multiple sessions
{"command": "git pull", "targets": ["session-id-1", "session-id-2"]}

// Watch for specific output
{"command": "docker build .", "wait": true, "watch_for": "output"}

// Monitor without executing
{"wait": true, "watch_for": "silence", "timeout": 10}
```

---

### control-char

Send control characters or special keys to a terminal session.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `key` | string | **Yes** | - | Key to send (see below) |
| `session_id` | string | No | current | Target session ID |
| `return_focus` | boolean | No | `true` | Return focus to Claude after sending |

**Available Keys:**

| Key | Meaning |
|-----|---------|
| `c` | Ctrl+C (SIGINT - interrupt) |
| `d` | Ctrl+D (EOF) |
| `z` | Ctrl+Z (SIGTSTP - suspend) |
| `a` | Ctrl+A (beginning of line) |
| `e` | Ctrl+E (end of line) |
| `k` | Ctrl+K (kill line forward) |
| `l` | Ctrl+L (clear screen) |
| `u` | Ctrl+U (kill line backward) |
| `w` | Ctrl+W (delete word) |
| `enter` | Enter/Return |
| `esc` | Escape |
| `tab` | Tab |
| `backspace` | Backspace |
| `up`, `down`, `left`, `right` | Arrow keys |
| `home`, `end` | Home / End |
| `pageup`, `pagedown` | Page Up / Page Down |
| `insert`, `delete` | Insert / Delete |
| `f1`–`f12` | Function keys |

**Examples:**

```json
// Interrupt running process
{"key": "c"}

// Clear screen
{"key": "l"}

// Send EOF
{"key": "d", "session_id": "specific-session-id"}
```

---

### paste

Paste text to a terminal session. Useful for multi-line content.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `text` | string | **Yes** | - | Text to paste |
| `session_id` | string | No | current | Target session ID |

**Examples:**

```json
// Paste simple text
{"text": "echo 'Hello World'"}

// Paste multi-line script
{"text": "for i in 1 2 3\ndo\n  echo $i\ndone"}
```

---

### clear

Clear the terminal screen.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | No | current | Target session ID |
| `return_focus` | boolean | No | `true` | Return focus to Claude after clearing |

**Examples:**

```json
// Clear current session
{}

// Clear specific session
{"session_id": "ABC123"}
```

---

## Terminal Reading

### read

Read terminal output from a session.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `lines` | integer | No | `20` | Number of lines to read |
| `session_id` | string | No | current | Target session ID |

**Examples:**

```json
// Read last 20 lines
{}

// Read last 100 lines from specific session
{"lines": 100, "session_id": "ABC123"}
```

---

## Session Management

### list

List all iTerm2 windows, tabs, and sessions.

**Parameters:** None

**Returns:** Formatted list of all windows with their tabs and sessions, including:
- Window ID
- Tab names and IDs
- Session IDs, names, current directory, and dimensions
- Indicators for Claude sessions (✳) and current session (●)

**Example:**

```json
{}
```

---

### focus

Focus a specific terminal session.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | **Yes** | - | Session ID to focus |

**Examples:**

```json
{"session_id": "ABC123-DEF456"}
```

---

### close-session

Close a terminal session.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | No | current | Session ID to close |
| `force` | boolean | No | `false` | Force close without confirmation |

**Examples:**

```json
// Close specific session
{"session_id": "ABC123", "force": true}

// Close current session
{"force": true}
```

---

### get-terminal-state

Get detailed state of the terminal.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | No | - | Get state of specific session only |

**Examples:**

```json
// Get full state
{}

// Get single session state
{"session_id": "ABC123"}
```

---

## Session Creation

### new-window

Create a new iTerm2 window.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `profile` | string | No | default | iTerm2 profile name |
| `command` | string | No | - | Command to run immediately |
| `return_focus` | boolean | No | `true` | Return focus to Claude after creation |

**Examples:**

```json
// Create simple window
{}

// Create window with specific profile and command
{"profile": "Dev", "command": "cd ~/projects"}
```

---

### new-tab

Create a new tab in the current window.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `profile` | string | No | default | iTerm2 profile name |
| `command` | string | No | - | Command to run immediately |
| `return_focus` | boolean | No | `true` | Return focus to Claude after creation |

**Examples:**

```json
// Create simple tab
{}

// Create tab with command
{"command": "npm run dev"}
```

---

### new-session

Smart session creation: splits current pane if window exists, otherwise creates new tab.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `profile` | string | No | default | iTerm2 profile name |

**Examples:**

```json
// Create session intelligently
{}

// Create with profile
{"profile": "Remote"}
```

---

### split

Split a pane to create a new terminal.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `direction` | string | **Yes** | - | `"h"` (horizontal) or `"v"` (vertical) |
| `session_id` | string | No | current | Session to split |
| `return_focus` | boolean | No | `true` | Return focus to Claude after split |

**Examples:**

```json
// Horizontal split
{"direction": "h"}

// Vertical split of specific session
{"direction": "v", "session_id": "ABC123"}
```

---

## Appearance

### set-appearance

Set tab title, badge, and/or color for a session.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | No | current | Target session |
| `title` | string | No | - | Tab title |
| `color` | string | No | - | Tab color (hex like `#FF0000` or name like `red`) |
| `badge` | string | No | - | Badge text |

**Available Colors:** `red`, `green`, `blue`, `yellow`, `purple`, `cyan`, `orange`, `pink`, `white`, or any hex color.

**Examples:**

```json
// Set all properties
{"title": "Dev Server", "badge": "3000", "color": "#00FF00"}

// Set just title
{"title": "Production", "session_id": "ABC123"}
```

---

### set-color-preset

Apply an iTerm2 color preset to a session.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `preset` | string | **Yes** | - | Preset name (use `list-color-presets` to see available) |
| `session_id` | string | No | current | Target session |

**Examples:**

```json
{"preset": "Solarized Dark"}
{"preset": "Tomorrow Night", "session_id": "ABC123"}
```

---

### list-color-presets

List all available iTerm2 color presets.

**Parameters:** None

**Returns:** Bulleted list of all available color preset names.

**Example:**

```json
{}
```

---

## Alerts

### show-alert

Show an iTerm2 alert dialog.

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `title` | string | **Yes** | - | Alert title |
| `message` | string | **Yes** | - | Alert message body |

**Examples:**

```json
{"title": "Build Complete", "message": "All tests passed!"}
```

---

## Error Handling

All tools return error messages in the following cases:

- **Session not found**: When a specified `session_id` doesn't exist
- **Not connected**: When iTerm2 connection is lost
- **Invalid parameters**: When required parameters are missing or invalid
- **Timeout**: When `execute` with `wait=true` exceeds the timeout
- **Permission denied**: When trying to affect Claude's own session (protected)

Error messages are returned as plain text starting with "Error:" or containing error details.

---

## Safety Notes

1. **Claude Protection**: The server automatically detects and prevents commands from affecting Claude Code's terminal session.

2. **Focus Management**: Use `return_focus: true` (default) to ensure focus returns to Claude after operations.

3. **Session Isolation**: Each command targets a specific session without affecting others.

4. **Timeout Protection**: All waiting operations have configurable timeouts to prevent hanging.
