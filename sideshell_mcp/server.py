"""sideshell MCP Server with multi-backend support.

An AI sidecar terminal: lets Claude/Cursor run commands in a visible, persistent
terminal you control. Pluggable backends: iTerm2, tmux, Ghostty (ghostty_tmux
hybrid), WezTerm, Kitty, maquake, and VSCode/IntelliJ via a local Unix socket.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, cast

from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    EmbeddedResource,
    ImageContent,
    Resource,
    ResourceTemplate,
    ServerCapabilities,
    TextContent,
    Tool,
)
from pydantic import AnyUrl

from .backends import (
    BackendType,
    TerminalBackend,
    get_backend,
    get_system_info,
    print_startup_info,
)
from .backends.base import ControlKey, SplitDirection

logger = logging.getLogger(__name__)


class SideshellServer:
    """MCP Server for terminal automation with pluggable backends."""

    def __init__(self, backend: TerminalBackend) -> None:
        """Initialize the server with a specific backend.

        Args:
            backend: Terminal backend to use.
        """
        self.server = Server("sideshell")
        self.backend = backend
        self.setup_handlers()

    def setup_handlers(self) -> None:
        """Set up all tool handlers."""

        # === Resources ===
        @self.server.list_resources()
        async def list_resources() -> list[Resource]:
            """List available resources."""
            return [
                Resource(
                    uri=AnyUrl("sideshell://sessions"),
                    name="Terminal Sessions",
                    description="List of all terminal sessions with metadata",
                    mimeType="application/json",
                ),
                Resource(
                    uri=AnyUrl("sideshell://capabilities"),
                    name="Backend Capabilities",
                    description="Current backend features and limitations",
                    mimeType="application/json",
                ),
            ]

        @self.server.list_resource_templates()
        async def list_resource_templates() -> list[ResourceTemplate]:
            """List resource templates for dynamic resources."""
            return [
                ResourceTemplate(
                    uriTemplate="sideshell://sessions/{session_id}",
                    name="Session Details",
                    description="Detailed info about a specific session",
                    mimeType="application/json",
                ),
                ResourceTemplate(
                    uriTemplate="sideshell://sessions/{session_id}/screen",
                    name="Session Screen",
                    description="Current screen content of a session",
                    mimeType="text/plain",
                ),
            ]

        @self.server.read_resource()
        async def read_resource(uri: str) -> list[ReadResourceContents]:
            """Read a resource by URI."""
            import json

            await self.backend.ensure_connection()

            # Convert AnyUrl to string if needed
            uri_str = str(uri)

            def make_result(text: str, mime: str = "text/plain") -> list[ReadResourceContents]:
                return [ReadResourceContents(content=text, mime_type=mime)]

            # Parse URI
            if uri_str == "sideshell://sessions":
                content = await self.backend.list_sessions()
                return make_result(content, "application/json")

            if uri_str == "sideshell://capabilities":
                sys_info = get_system_info()
                is_iterm = self.backend.name == "iterm2"
                caps = {
                    "backend": self.backend.name,
                    "features": {
                        "window_positioning": is_iterm,
                        "triggers": is_iterm,
                        "annotations": is_iterm,
                        "broadcast_input": True,
                        "color_presets": True,
                        "split_pane": True,
                        "tabs": True,
                        "windows": True,
                    },
                    "control_keys": [k.value for k in ControlKey],
                    "system": {
                        "platform": sys_info["platform"],
                        "current_terminal": sys_info["current_terminal"],
                        "available_backends": list(sys_info["available_terminals"].keys()),
                    },
                }
                return make_result(json.dumps(caps, indent=2), "application/json")

            # Dynamic resources: sideshell://sessions/{id}
            if uri_str.startswith("sideshell://sessions/"):
                parts = uri_str.replace("sideshell://sessions/", "").split("/")
                session_id = parts[0]

                if len(parts) == 1:
                    # Session details
                    content = await self.backend.get_terminal_state(session_id)
                    return make_result(content, "application/json")
                elif len(parts) == 2 and parts[1] == "screen":
                    # Screen content
                    content = await self.backend.read_terminal(lines=50, session_id=session_id)
                    return make_result(content)

            return make_result(f"Unknown resource: {uri_str}")

        # === Tools ===
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List all available tools."""
            return self._get_tool_definitions()

        @self.server.call_tool()
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[TextContent | ImageContent | EmbeddedResource]:
            """Handle tool calls."""
            logger.info(f"Tool called: {name} with args: {arguments}")

            try:
                await self.backend.ensure_connection()
                result = await self._route_tool_call(name, arguments)
                return [TextContent(type="text", text=str(result))]
            except Exception as e:
                logger.error(f"Error in tool {name}: {e}", exc_info=True)
                return [TextContent(type="text", text=f"Error: {e!s}")]

    def _get_tool_definitions(self) -> list[Tool]:
        """Get all tool definitions."""
        return [
            Tool(
                name="execute",
                description=(
                    f"Execute command in terminal ({self.backend.name}). "
                    "Supports single/multiple targets, wait for completion. Call 'list' first."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "Command to execute. Omit with wait=true to monitor. "
                                "Tip: prefix with a space to keep out of shell history "
                                "(e.g. for routine/repeated commands)."
                            ),
                        },
                        "session_id": {
                            "type": "string",
                            "description": "Target session (default: current)",
                        },
                        "targets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Multiple session IDs for broadcast",
                        },
                        "wait": {
                            "type": "boolean",
                            "default": False,
                            "description": "Wait for command completion",
                        },
                        "timeout": {
                            "type": "integer",
                            "default": 30,
                            "description": "Max seconds to wait (when wait=true)",
                        },
                        "watch_for": {
                            "type": "string",
                            "enum": ["prompt", "output", "silence"],
                            "default": "prompt",
                            "description": "Wait for: prompt/output/silence",
                        },
                        "return_focus": {
                            "type": "boolean",
                            "default": True,
                            "description": "Return focus to original session after execution",
                        },
                    },
                },
            ),
            Tool(
                name="read",
                description="Read terminal output. Use 'list' first to find session_id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "lines": {"type": "integer", "default": 20},
                        "session_id": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="control-char",
                description="Send control character: Ctrl+c/d/z, enter, esc, arrows, F1-F12, etc.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": [k.value for k in ControlKey]},
                        "session_id": {"type": "string"},
                        "return_focus": {
                            "type": "boolean",
                            "description": "Return focus after sending",
                            "default": True,
                        },
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="list",
                description=f"List all {self.backend.name} sessions. Call FIRST before execute.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="split",
                description="Split pane to create new terminal. Prefer reusing existing sessions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "enum": [d.value for d in SplitDirection],
                        },
                        "session_id": {"type": "string"},
                        "return_focus": {
                            "type": "boolean",
                            "description": "Return focus after split",
                            "default": True,
                        },
                    },
                    "required": ["direction"],
                },
            ),
            Tool(
                name="new-window",
                description="Create new window",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string"},
                        "command": {"type": "string"},
                        "return_focus": {"type": "boolean", "default": True},
                    },
                },
            ),
            Tool(
                name="new-tab",
                description="Create new tab",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string"},
                        "command": {"type": "string"},
                        "return_focus": {"type": "boolean", "default": True},
                    },
                },
            ),
            Tool(
                name="focus",
                description="Focus session",
                inputSchema={
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                },
            ),
            Tool(
                name="new-session",
                description="Create new session: split pane if window exists, else new tab.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string", "description": "Optional profile name"},
                    },
                },
            ),
            Tool(
                name="clear",
                description="Clear terminal screen",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "return_focus": {"type": "boolean", "default": True},
                    },
                },
            ),
            Tool(
                name="paste",
                description="Paste text to terminal (useful for multi-line content)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="set-appearance",
                description="Set tab appearance: title, color, badge. Backend-dependent.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "title": {"type": "string", "description": "Tab title"},
                        "color": {
                            "type": "string",
                            "description": "Tab color (hex like #FF0000 or name like red)",
                        },
                        "badge": {"type": "string", "description": "Badge text"},
                    },
                },
            ),
            Tool(
                name="get-terminal-state",
                description="Get terminal state (all sessions or specific session)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Optional: get state of specific session only",
                        },
                    },
                },
            ),
            Tool(
                name="show-alert",
                description="Show alert dialog. May not be supported by all backends.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["title", "message"],
                },
            ),
            Tool(
                name="set-color-preset",
                description="Change color scheme/preset. May not be supported by all backends.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "preset": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["preset"],
                },
            ),
            Tool(
                name="list-color-presets",
                description="List available color presets. May not be supported by all backends.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="close-session",
                description="Close a specific terminal pane/session by its ID.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Session ID to close",
                        },
                        "force": {
                            "type": "boolean",
                            "default": False,
                            "description": "Close even if it looks like an AI session",
                        },
                    },
                    "required": ["session_id"],
                },
            ),
        ]

    async def _route_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        """Route tool call to appropriate handler."""
        # Handle return_focus for applicable tools
        return_focus = arguments.pop("return_focus", True)
        original_session = await self.backend.get_current_active_session_id() if return_focus else None

        async def _do_return_focus(result: str) -> str:
            if return_focus and original_session:
                current = await self.backend.get_current_active_session_id()
                if current and current != original_session:
                    await asyncio.sleep(0.3)
                    await self.backend.focus_session(original_session)
                    return f"{result} (focus returned)"
            return result

        match name:
            case "execute":
                result = await self._execute(arguments)
                return await _do_return_focus(result)

            case "read":
                return await self.backend.read_terminal(
                    lines=arguments.get("lines", 20),
                    session_id=arguments.get("session_id"),
                )

            case "control-char":
                try:
                    key = ControlKey(arguments["key"])
                except ValueError:
                    return f"Invalid control key: {arguments['key']}"
                result = await self.backend.send_control(key, arguments.get("session_id"))
                return await _do_return_focus(result)

            case "list":
                return await self.backend.list_sessions()

            case "split":
                try:
                    direction = SplitDirection(arguments["direction"])
                except ValueError:
                    return f"Invalid direction: {arguments['direction']}"
                result = await self.backend.split_pane(direction, arguments.get("session_id"))
                return await _do_return_focus(result)

            case "new-window":
                result = await self.backend.create_window(
                    profile=arguments.get("profile"),
                    command=arguments.get("command"),
                )
                return await _do_return_focus(result)

            case "new-tab":
                result = await self.backend.create_tab(
                    profile=arguments.get("profile"),
                    command=arguments.get("command"),
                )
                return await _do_return_focus(result)

            case "focus":
                return await self.backend.focus_session(arguments["session_id"])

            case "new-session":
                return await self.backend.create_session(arguments.get("profile"))

            case "clear":
                result = await self.backend.clear_terminal(arguments.get("session_id"))
                return await _do_return_focus(result)

            case "paste":
                return await self.backend.send_text(
                    arguments["text"],
                    arguments.get("session_id"),
                )

            case "set-appearance":
                return await self.backend.set_appearance(
                    session_id=arguments.get("session_id"),
                    title=arguments.get("title"),
                    color=arguments.get("color"),
                    badge=arguments.get("badge"),
                )

            case "get-terminal-state":
                return await self.backend.get_terminal_state(arguments.get("session_id"))

            case "show-alert":
                return await self.backend.show_alert(
                    arguments["title"],
                    arguments["message"],
                )

            case "set-color-preset":
                return await self.backend.set_color_preset(
                    arguments["preset"],
                    arguments.get("session_id"),
                )

            case "list-color-presets":
                return await self.backend.list_color_presets()

            case "close-session":
                return await self.backend.close_session(
                    arguments.get("session_id"),
                    force=arguments.get("force", False),
                )

            case _:
                return f"Unknown tool: {name}"

    async def _execute(self, args: dict[str, Any]) -> str:
        """Handle execute command with optional broadcast."""
        command: str | None = args.get("command")
        session_id: str | None = args.get("session_id")
        targets: list[str] | None = args.get("targets")
        wait: bool = args.get("wait", False)
        timeout: int = args.get("timeout", 30)
        watch_for: str = args.get("watch_for", "prompt")

        if not command and not wait:
            return "Error: command is required (or use wait=true to monitor session)"

        # Broadcast to multiple targets
        if targets and command:
            results = []
            skipped = 0
            for target in targets:
                if await self.backend.is_ai_session(target):
                    skipped += 1
                    continue
                await self.backend.execute_command(command, target, wait=False)
                results.append(target)

            result = f"Sent to {len(results)} sessions: {command}"
            if skipped > 0:
                result += f"\nSkipped {skipped} AI session(s)"
            return result

        # Single session execute
        if not command and wait:
            # Monitor only mode
            return await self.backend.execute_command("", session_id, wait=True, timeout=timeout, watch_for=watch_for)

        return await self.backend.execute_command(
            command or "",
            session_id,
            wait=wait,
            timeout=timeout,
            watch_for=watch_for,
        )

    async def run(self) -> None:
        """Run the MCP server."""
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="sideshell",
                        server_version="1.0.0",
                        capabilities=cast(
                            ServerCapabilities,
                            {
                                "tools": {},
                                "resources": {},
                            },
                        ),
                    ),
                )
        except* Exception as eg:
            for i, exc in enumerate(eg.exceptions, 1):
                logger.error("Sub-exception #%d: %r", i, exc, exc_info=exc)
            raise


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="sideshell",
        description="AI sidecar terminal - let Claude/Cursor run commands in a visible terminal",
    )
    parser.add_argument(
        "--backend",
        "-b",
        type=str,
        choices=[
            "auto",
            "iterm2",
            "tmux",
            "wezterm",
            "kitty",
            "ghostty",
            "ghostty_tmux",
            "maquake",
            "vscode",
            "intellij",
        ],
        default="auto",
        help="Terminal backend to use (default: auto-detect)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="sideshell 1.0.0",
    )
    return parser.parse_args()


async def main_async(backend_type: BackendType = BackendType.AUTO) -> None:
    """Main entry point (async).

    Args:
        backend_type: Backend type to use.
    """
    backend = get_backend(backend_type)
    logger.info(f"Using backend: {backend.name}")

    server = SideshellServer(backend)
    await server.run()


def main() -> None:
    """Console script entry point (sync)."""
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Log system info at startup
    startup_info = print_startup_info()
    for line in startup_info.split("\n"):
        logger.info(line)

    # Map string to enum
    backend_map = {
        "auto": BackendType.AUTO,
        "iterm2": BackendType.ITERM2,
        "tmux": BackendType.TMUX,
        "wezterm": BackendType.WEZTERM,
        "kitty": BackendType.KITTY,
        "ghostty": BackendType.GHOSTTY,
        "ghostty_tmux": BackendType.GHOSTTY,
        "maquake": BackendType.MAQUAKE,
        "vscode": BackendType.VSCODE,
        "intellij": BackendType.INTELLIJ,
    }
    backend_type = backend_map.get(args.backend, BackendType.AUTO)

    try:
        asyncio.run(main_async(backend_type))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


def cli_main() -> None:
    """Legacy CLI entry point."""
    main()


# Backwards-compatible alias for the pre-rename class name.
VibeSideshellServer = SideshellServer


if __name__ == "__main__":
    cli_main()
