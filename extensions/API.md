# Sideshell IDE Plugin API

WebSocket bridge protocol for controlling IDE terminals from MCP clients.

## Architecture

```
┌─────────────────┐    WebSocket     ┌──────────────────┐
│  sideshell MCP  │◄───JSON-RPC 2.0──►│  IDE Plugin      │
│  (Python)       │                   │  (VSCode/IntelliJ)│
└─────────────────┘                   └──────────────────┘
        │                                     │
  reads port file                     writes port file
        │                                     │
        └──── ~/.sideshell/<ide>-port ────────┘
```

## Security

Two-layer authentication:

### Layer 1: Token Auth

On startup, the plugin generates a random 256-bit token and writes it to the
port file with `0600` permissions (owner-readable only).

Port file format (`~/.sideshell/<ide>-port`):
```json
{
  "port": 46117,
  "pid": 12345,
  "token": "a1b2c3d4e5f6...",
  "ide": "vscode",
  "version": "0.1.0"
}
```

The client must include the token as a query parameter when connecting:
```
ws://127.0.0.1:46117?token=a1b2c3d4e5f6...
```

Connections without a valid token are rejected with HTTP 401 (VSCode) or
WebSocket close code 4003 (IntelliJ).

### Layer 2: User Consent

On the first authenticated connection, the plugin shows a dialog in the IDE:

> **Sideshell wants to access your IDE terminals.**
> This allows an MCP client to read terminal output and execute commands.
> [Allow] [Deny]

Until the user clicks **Allow**, all JSON-RPC requests return error code `-32001`.

If the user clicks **Deny**:
- The token is regenerated (invalidating the port file for the denied client)
- The WebSocket connection is closed with code `4001`

Approval is per-session (resets when the IDE restarts).

### Security Properties

| Threat | Mitigation |
|--------|-----------|
| Remote attacker | Server binds to `127.0.0.1` only |
| Other users on same machine | Port file has `0600` permissions |
| Malicious local process (same user) | User consent dialog in IDE |
| Token replay after IDE restart | New token generated each startup |

## Transport

- **Protocol**: JSON-RPC 2.0 over WebSocket
- **Binding**: `127.0.0.1` (localhost only)
- **Default ports**: VSCode `46117`, IntelliJ `46118`

### Request format
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "list_sessions",
  "params": {}
}
```

### Response format
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": [...]
}
```

### Error format
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32603,
    "message": "Error description"
  }
}
```

## JSON-RPC Methods

### Session Management

#### `list_sessions`

List all terminal sessions.

**Params**: none

**Result**: `SessionInfo[]`

```json
[
  {
    "id": "term-1",
    "name": "zsh",
    "path": "/home/user/project",
    "job": "zsh",
    "active": true,
    "at_prompt": false,
    "project": "my-project"
  }
]
```

#### `get_active_session`

Get the currently focused terminal.

**Params**: none

**Result**: `{ "session_id": string | null }`

```json
{ "session_id": "term-1" }
```

#### `is_ai_session`

Check if a terminal is an AI session (Claude, Copilot, Cursor, etc.).

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Terminal ID |

**Result**: `boolean`

#### `focus_session`

Focus/activate a terminal tab.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | yes | Terminal ID |

**Result**: `string` (confirmation message)

#### `close_session`

Close a terminal.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Terminal ID (default: active) |

**Result**: `string`

### Reading Output

#### `read_terminal`

Read buffered output lines from a terminal.

**Params**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | no | active | Terminal ID |
| `lines` | int | no | 20 | Number of lines |

**Result**: `string` (output text)

Note: Output capture requires shell integration (Bash/Zsh/PowerShell).

#### `get_terminal_state`

Get terminal state information.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Specific terminal, or all if omitted |

**Result** (specific terminal):
```json
{
  "id": "term-1",
  "name": "zsh",
  "buffer_lines": 42
}
```

**Result** (all terminals):
```json
{
  "terminals": [...],
  "total": 3,
  "active": "term-1"
}
```

### Writing / Executing

#### `execute_command`

Execute a command in a terminal (sends text + Enter).

**Params**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `command` | string | yes | | Command to execute |
| `session_id` | string | no | active | Terminal ID |
| `wait` | bool | no | false | Wait for completion |
| `timeout` | int | no | 30 | Wait timeout in seconds |
| `watch_for` | string | no | "prompt" | What to wait for |

**Result**: `string` (confirmation or output if wait=true)

Refuses to execute in AI terminals (Claude, Copilot, Cursor).

#### `send_text`

Send raw text to a terminal (without Enter).

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `text` | string | yes | Text to send |
| `session_id` | string | no | Terminal ID (default: active) |

**Result**: `string`

#### `send_control`

Send a control character/key.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `key` | string | yes | Key name (see table) |
| `session_id` | string | no | Terminal ID (default: active) |

Supported keys:

| Key | Character | Description |
|-----|-----------|-------------|
| `c` | Ctrl+C | Interrupt |
| `d` | Ctrl+D | EOF |
| `z` | Ctrl+Z | Suspend |
| `a` | Ctrl+A | Beginning of line |
| `e` | Ctrl+E | End of line |
| `k` | Ctrl+K | Kill to end of line |
| `l` | Ctrl+L | Clear screen |
| `u` | Ctrl+U | Kill to beginning |
| `w` | Ctrl+W | Delete word |
| `enter` | CR | Enter/Return |
| `esc` | ESC | Escape |
| `tab` | TAB | Tab |
| `backspace` | DEL | Backspace |
| `up` | ESC[A | Arrow up |
| `down` | ESC[B | Arrow down |
| `right` | ESC[C | Arrow right |
| `left` | ESC[D | Arrow left |

**Result**: `string`

#### `clear_terminal`

Clear terminal screen and output buffer.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Terminal ID (default: active) |

**Result**: `string`

### Creating Terminals

#### `create_tab`

Create a new terminal tab.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `profile` | string | no | Terminal profile/name |
| `command` | string | no | Command to run after creation |

**Result**: `{ "new_session_id": string }`

#### `create_window`

Create a new terminal window (VSCode: opens in editor area; IntelliJ: creates tab).

**Params**: same as `create_tab`

**Result**: `{ "new_session_id": string }`

#### `split_pane`

Split the current terminal pane (VSCode: creates split; IntelliJ: creates tab).

**Params**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | no | active | Terminal to split |
| `direction` | string | no | "v" | "v" (vertical) or "h" (horizontal) |

**Result**: `{ "new_session_id": string }`

### Appearance

#### `set_appearance`

Set terminal appearance (limited by IDE API).

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Terminal ID |
| `title` | string | no | Tab title |
| `color` | string | no | Tab color (hex) |
| `badge` | string | no | Badge text |

**Result**: `string`

## Error Codes

| Code | Meaning |
|------|---------|
| `-32001` | Waiting for user approval |
| `-32603` | Internal error |
| `-32700` | Parse error (invalid JSON) |
| `4001` | WebSocket close: access denied by user |
| `4003` | WebSocket close: invalid token |

## Session ID Format

- **VSCode**: `term-{counter}` (e.g., `term-1`, `term-2`)
- **IntelliJ**: `term-{projectName}-{index}` (e.g., `term-myproject-0`)

## Port File Locations

| IDE | Port file | Default port |
|-----|-----------|-------------|
| VSCode/Cursor | `~/.sideshell/vscode-port` | 46117 |
| IntelliJ/PyCharm/WebStorm/... | `~/.sideshell/intellij-port` | 46118 |

## Python Client Usage

```python
from sideshell_mcp.backends.ide_bridge import IDEBridgeClient

client = IDEBridgeClient("vscode", 46117)
await client.connect()  # reads token from port file automatically

sessions = await client.list_sessions()
await client.execute_command("ls -la", session_id="term-1")
output = await client.read_terminal("term-1", lines=20)

await client.disconnect()
```
