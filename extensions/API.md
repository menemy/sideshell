# Sideshell IDE Plugin API

Unix socket bridge protocol for controlling IDE terminals from MCP clients.

## Architecture

```
┌─────────────────┐   Unix socket    ┌──────────────────┐
│  sideshell MCP  │◄──JSON-RPC 2.0──►│  IDE Plugin      │
│  (Python)       │  (newline JSON)  │  (VSCode/IntelliJ)│
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
  "socket": "/Users/user/.sideshell/vscode.sock",
  "pid": 12345,
  "token": "a1b2c3d4e5f6...",
  "ide": "vscode",
  "version": "0.3.0"
}
```

The client must send a token handshake as the first message after connecting:
```json
{"type": "auth", "token": "a1b2c3d4e5f6..."}
```

Response:
```json
{"ok": true}
```

Invalid token:
```json
{"ok": false, "error": "invalid token"}
```

### Layer 2: User Consent

On the first authenticated connection, the plugin shows a dialog in the IDE:

> **Sideshell wants to access your IDE terminals.**
> This allows an MCP client to read terminal output and execute commands.
> [Allow] [Deny]

Until the user clicks **Allow**, all JSON-RPC requests return error code `-32001`.

Approval is **persisted** in IDE settings:
- **VSCode/Cursor**: `sideshell.allowAccess` in settings
- **IntelliJ**: `approved` in sideshell.xml (Settings → sideshell)

### Security Properties

| Threat | Mitigation |
|--------|-----------|
| Remote attacker | Unix socket (not network-accessible) |
| Other users on same machine | Socket file has `0600` permissions |
| Malicious local process (same user) | User consent dialog in IDE |
| Token replay after IDE restart | New token generated each startup |

## Transport

- **Protocol**: JSON-RPC 2.0 over Unix domain socket
- **Framing**: Newline-delimited JSON (one message per line)
- **Sockets**: `~/.sideshell/vscode.sock`, `~/.sideshell/intellij.sock`

### Connection sequence

```
Client                              Server
  │                                    │
  ├──── connect to unix socket ───────►│
  │                                    │
  ├──── {"type":"auth","token":"..."} ►│
  │                                    │
  │◄─── {"ok":true}                ────┤
  │                                    │
  ├──── JSON-RPC request ─────────────►│
  │◄─── JSON-RPC response ────────────┤
  │                                    │
  ├──── JSON-RPC request ─────────────►│
  │◄─── JSON-RPC response ────────────┤
  ...
```

### Request format
```json
{"jsonrpc": "2.0", "id": 1, "method": "list_sessions", "params": {}}
```

### Response format
```json
{"jsonrpc": "2.0", "id": 1, "result": [...]}
```

### Error format
```json
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "Error description"}}
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

#### `get_terminal_state`

Get terminal state information.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Specific terminal, or all if omitted |

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

Supported keys: `c`, `d`, `z`, `a`, `e`, `k`, `l`, `u`, `w`, `enter`, `esc`, `tab`, `backspace`, `up`, `down`, `right`, `left`

#### `clear_terminal`

Clear terminal screen and output buffer.

**Params**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `session_id` | string | no | Terminal ID (default: active) |

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

Create a new terminal window.

**Params**: same as `create_tab`

#### `split_pane`

Split the current terminal pane.

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

## Error Codes

| Code | Meaning |
|------|---------|
| `-32001` | Waiting for user approval |
| `-32603` | Internal error |
| `-32700` | Parse error (invalid JSON) |

## Session ID Format

- **VSCode**: `term-{counter}` (e.g., `term-1`, `term-2`)
- **IntelliJ**: `term-{projectName}-{index}` (e.g., `term-myproject-0`)

## Python Client Usage

```python
from sideshell_mcp.backends.ide_bridge import IDEBridgeClient

client = IDEBridgeClient("vscode", 46117)
await client.connect()  # reads token from port file, connects to unix socket

sessions = await client.list_sessions()
await client.execute_command("ls -la", session_id="term-1")
output = await client.read_terminal("term-1", lines=20)

await client.disconnect()
```
