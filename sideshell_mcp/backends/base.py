"""Abstract base class for terminal backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar


class BackendType(str, Enum):
    """Available terminal backends."""

    ITERM2 = "iterm2"
    TMUX = "tmux"
    WEZTERM = "wezterm"
    KITTY = "kitty"
    GHOSTTY = "ghostty"
    MAQUAKE = "maquake"
    VSCODE = "vscode"
    INTELLIJ = "intellij"
    AUTO = "auto"


class ControlKey(str, Enum):
    """Control key enumeration."""

    # Ctrl keys
    C = "c"  # Ctrl+C (SIGINT)
    D = "d"  # Ctrl+D (EOF)
    Z = "z"  # Ctrl+Z (SIGTSTP)
    A = "a"  # Ctrl+A (beginning of line)
    E = "e"  # Ctrl+E (end of line)
    K = "k"  # Ctrl+K (kill line)
    L = "l"  # Ctrl+L (clear screen)
    U = "u"  # Ctrl+U (kill line backward)
    W = "w"  # Ctrl+W (delete word)
    ENTER = "enter"  # Enter/Return key
    ESC = "esc"  # Escape key
    TAB = "tab"  # Tab key
    BACKSPACE = "backspace"  # Backspace key

    # Arrow keys
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

    # Navigation keys
    HOME = "home"
    END = "end"
    PAGE_UP = "pageup"
    PAGE_DOWN = "pagedown"
    INSERT = "insert"
    DELETE = "delete"

    # Function keys
    F1 = "f1"
    F2 = "f2"
    F3 = "f3"
    F4 = "f4"
    F5 = "f5"
    F6 = "f6"
    F7 = "f7"
    F8 = "f8"
    F9 = "f9"
    F10 = "f10"
    F11 = "f11"
    F12 = "f12"


class SplitDirection(str, Enum):
    """Split direction enumeration."""

    HORIZONTAL = "h"
    VERTICAL = "v"


class AnnotationType(str, Enum):
    """Annotation type for screen analysis."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    SUCCESS = "success"


@dataclass
class Annotation:
    """Single annotation on terminal output."""

    line: int
    column: int
    length: int
    type: AnnotationType
    text: str  # The matched text
    note: str  # AI-generated note


@dataclass
class AnnotationResult:
    """Result of annotate_screen operation."""

    annotations: list[Annotation]
    backend: str
    native_annotations: bool  # True if annotations are clickable in terminal
    total_lines_scanned: int


# Default patterns for auto-detection
DEFAULT_ANNOTATION_PATTERNS: dict[AnnotationType, list[str]] = {
    AnnotationType.ERROR: [
        r"\[ERROR\]",
        r"\bError:",
        r"\berror:",
        r"\bERROR\b",
        r"\bFAILED\b",
        r"\bFail\b",
        r"\bException\b",
        r"\bTraceback\b",
        r"panic:",
        r"fatal:",
        r"FATAL:",
    ],
    AnnotationType.WARNING: [
        r"\[WARNING\]",
        r"\[WARN\]",
        r"\bWarning:",
        r"\bwarning:",
        r"\bWARN\b",
        r"\bdeprecated\b",
    ],
    AnnotationType.SUCCESS: [
        r"\[OK\]",
        r"\bPASSED\b",
        r"\bSuccess\b",
        r"\bsuccess\b",
        r"✓",
        r"✔",
    ],
}


@dataclass
class SessionInfo:
    """Session information."""

    session_id: str
    name: str
    path: str
    job: str
    at_prompt: bool
    columns: int = 0
    rows: int = 0
    tty: str | None = None


@dataclass
class TerminalState:
    """Full terminal state."""

    windows: list[dict[str, Any]]
    total_sessions: int
    active_window: str | None
    active_tab: str | None
    active_session: str | None


class TerminalBackend(ABC):
    """Abstract base class for terminal backends.

    All terminal backends must implement these methods to provide
    a consistent interface for the MCP server.
    """

    # Control character mappings
    CONTROL_CHARS: ClassVar[dict[ControlKey, str]] = {
        # Ctrl keys
        ControlKey.C: "\x03",
        ControlKey.D: "\x04",
        ControlKey.Z: "\x1a",
        ControlKey.A: "\x01",
        ControlKey.E: "\x05",
        ControlKey.K: "\x0b",
        ControlKey.L: "\x0c",
        ControlKey.U: "\x15",
        ControlKey.W: "\x17",
        ControlKey.ENTER: "\n",
        ControlKey.ESC: "\x1b",
        ControlKey.TAB: "\t",
        ControlKey.BACKSPACE: "\x7f",
        # Arrow keys (normal mode)
        ControlKey.UP: "\x1b[A",
        ControlKey.DOWN: "\x1b[B",
        ControlKey.RIGHT: "\x1b[C",
        ControlKey.LEFT: "\x1b[D",
        # Navigation keys
        ControlKey.HOME: "\x1b[H",
        ControlKey.END: "\x1b[F",
        ControlKey.PAGE_UP: "\x1b[5~",
        ControlKey.PAGE_DOWN: "\x1b[6~",
        ControlKey.INSERT: "\x1b[2~",
        ControlKey.DELETE: "\x1b[3~",
        # Function keys
        ControlKey.F1: "\x1bOP",
        ControlKey.F2: "\x1bOQ",
        ControlKey.F3: "\x1bOR",
        ControlKey.F4: "\x1bOS",
        ControlKey.F5: "\x1b[15~",
        ControlKey.F6: "\x1b[17~",
        ControlKey.F7: "\x1b[18~",
        ControlKey.F8: "\x1b[19~",
        ControlKey.F9: "\x1b[20~",
        ControlKey.F10: "\x1b[21~",
        ControlKey.F11: "\x1b[23~",
        ControlKey.F12: "\x1b[24~",
    }

    @staticmethod
    def _real_output_lines(new_lines: list[str], command: str) -> list[str]:
        """Filter the echoed command line out of newly-appeared lines.

        When a command is submitted the shell echoes the command text on the
        prompt line, which would otherwise be mistaken for command output by
        ``watch_for='output'``. Any new line containing the (stripped) command
        text is treated as that echo and dropped; the rest is real output.
        """
        cmd = command.strip()
        candidates = [line for line in new_lines if line.strip()]
        if not cmd:
            return candidates
        return [line for line in candidates if cmd not in line]

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the backend name (e.g., 'iterm2', 'tmux')."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available on the system."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the terminal.

        Returns:
            True if connection successful, False otherwise.
        """
        ...

    @abstractmethod
    async def ensure_connection(self) -> None:
        """Ensure connection is active, reconnect if needed."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the terminal."""
        ...

    # Session Management

    @abstractmethod
    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        """Get session by ID or current active session.

        Args:
            session_id: Optional session ID. If None, returns current session.

        Returns:
            SessionInfo or None if not found.
        """
        ...

    @abstractmethod
    async def list_sessions(self) -> str:
        """List all sessions with pane info.

        Returns:
            Formatted string with session listing.
        """
        ...

    @abstractmethod
    async def get_terminal_state(self, session_id: str | None = None) -> str:
        """Get detailed terminal state.

        Args:
            session_id: Optional session ID for single session info.

        Returns:
            JSON string with terminal state.
        """
        ...

    @abstractmethod
    async def is_ai_session(self, session_id: str) -> bool:
        """Check if session is running AI tool (Claude, etc.).

        Args:
            session_id: Session ID to check.

        Returns:
            True if session is AI session.
        """
        ...

    @abstractmethod
    async def get_current_active_session_id(self) -> str | None:
        """Get the currently active/focused session ID.

        Returns:
            Session ID or None.
        """
        ...

    # Command Execution

    @abstractmethod
    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,
        watch_for: str = "prompt",
    ) -> str:
        """Execute command in terminal.

        Args:
            command: Command to execute.
            session_id: Target session ID.
            wait: Wait for completion.
            timeout: Timeout in seconds.
            watch_for: What to wait for ('prompt', 'output', 'silence').

        Returns:
            Result string.
        """
        ...

    @abstractmethod
    async def send_text(self, text: str, session_id: str | None = None) -> str:
        """Send text to terminal (paste).

        Args:
            text: Text to send.
            session_id: Target session ID.

        Returns:
            Result string.
        """
        ...

    @abstractmethod
    async def send_control(self, key: ControlKey, session_id: str | None = None) -> str:
        """Send control character.

        Args:
            key: Control key to send.
            session_id: Target session ID.

        Returns:
            Result string.
        """
        ...

    # Terminal Reading

    @abstractmethod
    async def read_terminal(self, lines: int = 20, session_id: str | None = None) -> str:
        """Read terminal output.

        Args:
            lines: Number of lines to read.
            session_id: Target session ID.

        Returns:
            Terminal output string.
        """
        ...

    @abstractmethod
    async def clear_terminal(self, session_id: str | None = None) -> str:
        """Clear terminal screen.

        Args:
            session_id: Target session ID.

        Returns:
            Result string.
        """
        ...

    # Session Creation

    @abstractmethod
    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        """Split pane to create new terminal.

        Args:
            direction: Split direction (horizontal/vertical).
            session_id: Source session ID.

        Returns:
            Result string with new session ID.
        """
        ...

    @abstractmethod
    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new window.

        Args:
            profile: Profile name.
            command: Initial command.

        Returns:
            Result string with new session ID.
        """
        ...

    @abstractmethod
    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new tab.

        Args:
            profile: Profile name.
            command: Initial command.

        Returns:
            Result string with new session ID.
        """
        ...

    @abstractmethod
    async def create_session(self, profile: str | None = None) -> str:
        """Smart session creation (split if window exists, else new tab).

        Args:
            profile: Profile name.

        Returns:
            Result string with new session ID.
        """
        ...

    # Focus Management

    @abstractmethod
    async def focus_session(self, session_id: str) -> str:
        """Focus specific session.

        Args:
            session_id: Session to focus.

        Returns:
            Result string.
        """
        ...

    @abstractmethod
    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        """Close session.

        Args:
            session_id: Session to close.
            force: Force close without confirmation.

        Returns:
            Result string.
        """
        ...

    # Appearance (optional, may not be supported by all backends)

    async def set_appearance(
        self,
        session_id: str | None = None,
        title: str | None = None,
        color: str | None = None,
        badge: str | None = None,
    ) -> str:
        """Set tab/session appearance.

        Args:
            session_id: Target session ID.
            title: Tab title.
            color: Tab color.
            badge: Badge text.

        Returns:
            Result string.
        """
        return "Appearance settings not supported by this backend"

    async def set_color_preset(self, preset: str, session_id: str | None = None) -> str:
        """Set color preset.

        Args:
            preset: Preset name.
            session_id: Target session ID.

        Returns:
            Result string.
        """
        return "Color presets not supported by this backend"

    async def list_color_presets(self) -> str:
        """List available color presets.

        Returns:
            List of presets.
        """
        return "Color presets not supported by this backend"

    # Alerts (optional)

    async def show_alert(self, title: str, message: str) -> str:
        """Show alert dialog.

        Args:
            title: Alert title.
            message: Alert message.

        Returns:
            Result string.
        """
        return "Alerts not supported by this backend"

    # Screen Analysis (optional, with graceful degradation)

    async def annotate_screen(
        self,
        session_id: str | None = None,
        patterns: dict[AnnotationType, list[str]] | None = None,
        custom_notes: dict[str, str] | None = None,
        lines: int = 50,
    ) -> AnnotationResult:
        """Analyze screen content and add annotations for errors/warnings.

        This method scans terminal output for patterns (errors, warnings, etc.)
        and adds annotations. On backends that support native annotations
        (iTerm2), clickable markers are added. On other backends, returns
        analysis results only.

        Args:
            session_id: Target session ID.
            patterns: Custom patterns dict {AnnotationType: [regex patterns]}.
                     If None, uses DEFAULT_ANNOTATION_PATTERNS.
            custom_notes: Custom notes for specific patterns {pattern: note}.
            lines: Number of lines to scan (default 50).

        Returns:
            AnnotationResult with list of annotations and backend info.
        """
        import re

        # Get patterns to use
        active_patterns = patterns or DEFAULT_ANNOTATION_PATTERNS

        # Read terminal content
        content = await self.read_terminal(lines=lines, session_id=session_id)

        # Parse content into lines
        content_lines = content.split("\n")
        annotations: list[Annotation] = []

        # Default notes for each type
        default_notes = {
            AnnotationType.ERROR: "Error detected - needs attention",
            AnnotationType.WARNING: "Warning - review recommended",
            AnnotationType.SUCCESS: "Success indicator",
            AnnotationType.INFO: "Information",
        }

        # Scan each line for patterns
        for line_num, line_text in enumerate(content_lines):
            for ann_type, type_patterns in active_patterns.items():
                for pattern in type_patterns:
                    for match in re.finditer(pattern, line_text, re.IGNORECASE):
                        # Determine note
                        if custom_notes and pattern in custom_notes:
                            note = custom_notes[pattern]
                        else:
                            note = default_notes.get(ann_type, "")

                        annotations.append(
                            Annotation(
                                line=line_num,
                                column=match.start(),
                                length=match.end() - match.start(),
                                type=ann_type,
                                text=line_text[max(0, match.start() - 10) : match.end() + 30].strip(),
                                note=note,
                            )
                        )
                        break  # Only one annotation per pattern per line

        return AnnotationResult(
            annotations=annotations,
            backend=self.name,
            native_annotations=False,  # Override in backends that support it
            total_lines_scanned=len(content_lines),
        )
