"""Backend detection and factory.

Detection priority:
1. Parent process tree analysis (who launched the MCP server?)
2. Environment variables (TERM_PROGRAM, ITERM_SESSION_ID, etc.)
3. Available binaries / port files
4. Platform-based fallback
"""

from __future__ import annotations

import logging
import os
import shutil

from .base import BackendType, TerminalBackend

logger = logging.getLogger(__name__)


def detect_parent_process() -> BackendType | None:
    """Detect terminal/IDE by walking the parent process tree.

    Walks up from the current process to find which terminal or IDE
    spawned the MCP server. This gives the most accurate detection
    because it tells us exactly who is the caller.

    Returns:
        BackendType if detected, None otherwise.
    """
    try:
        import subprocess

        pid = os.getpid()
        visited = set()

        while pid and pid > 1 and pid not in visited:
            visited.add(pid)
            try:
                # Get parent PID and process name
                result = subprocess.run(
                    ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode != 0:
                    break

                line = result.stdout.strip()
                if not line:
                    break

                parts = line.split(None, 1)
                if len(parts) < 2:
                    break

                ppid_str, comm = parts
                ppid = int(ppid_str.strip())
                comm = comm.strip().lower()

                # Also get the full command line for better detection
                cmdline_result = subprocess.run(
                    ["ps", "-o", "args=", "-p", str(ppid)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                cmdline = cmdline_result.stdout.strip().lower() if cmdline_result.returncode == 0 else ""

                # Check for VSCode / Cursor
                if any(x in comm for x in ["code", "cursor", "electron"]):
                    if "cursor" in comm or "cursor" in cmdline:
                        logger.info("Parent process detected: Cursor (using vscode backend)")
                    else:
                        logger.info("Parent process detected: VS Code")
                    return BackendType.VSCODE

                # Check for IntelliJ-based IDEs
                intellij_markers = [
                    "idea",
                    "pycharm",
                    "webstorm",
                    "goland",
                    "rustrover",
                    "phpstorm",
                    "rider",
                    "clion",
                    "datagrip",
                    "dataspell",
                    "android studio",
                    "studio",
                ]
                if any(x in comm for x in intellij_markers):
                    logger.info(f"Parent process detected: JetBrains IDE ({comm})")
                    return BackendType.INTELLIJ
                if "java" in comm and any(x in cmdline for x in intellij_markers):
                    logger.info(f"Parent process detected: JetBrains IDE (java -> {cmdline[:80]})")
                    return BackendType.INTELLIJ

                # Check for iTerm2
                if "iterm" in comm or "iterm2" in comm:
                    logger.info("Parent process detected: iTerm2")
                    return BackendType.ITERM2

                # Check for tmux
                if "tmux" in comm:
                    logger.info("Parent process detected: tmux")
                    return BackendType.TMUX

                # Check for WezTerm
                if "wezterm" in comm:
                    logger.info("Parent process detected: WezTerm")
                    return BackendType.WEZTERM

                # Check for Kitty
                if "kitty" in comm:
                    logger.info("Parent process detected: Kitty")
                    return BackendType.KITTY

                # Check for Ghostty
                if "ghostty" in comm:
                    logger.info("Parent process detected: Ghostty")
                    return BackendType.GHOSTTY

                # Check for maquake
                if "maquake" in comm:
                    logger.info("Parent process detected: maquake")
                    return BackendType.MAQUAKE

                pid = ppid
            except (ValueError, subprocess.TimeoutExpired):
                break

    except Exception as e:
        logger.debug(f"Parent process detection failed: {e}")

    return None


def detect_ghostty() -> bool:
    """Check if Ghostty terminal is available.

    Detection methods:
    1. Check TERM_PROGRAM env var
    2. Check GHOSTTY_RESOURCES_DIR env var
    3. Check if ghostty binary exists
    """
    # Check TERM_PROGRAM
    if os.environ.get("TERM_PROGRAM") == "ghostty":
        logger.debug("Ghostty detected via TERM_PROGRAM")
        return True

    # Ghostty sets this env var
    if os.environ.get("GHOSTTY_RESOURCES_DIR"):
        logger.debug("Ghostty detected via GHOSTTY_RESOURCES_DIR")
        return True

    # Check if ghostty binary exists
    if shutil.which("ghostty"):
        logger.debug("Ghostty binary found in PATH")
        return True

    return False


def detect_vscode() -> bool:
    """Check if VSCode/Cursor is available.

    Detection methods:
    1. Check TERM_PROGRAM env var
    2. Check VSCODE_* env vars (set in VSCode integrated terminal)
    3. Check port file (~/.sideshell/vscode-port)
    4. Check if 'code' binary exists
    """
    # Check TERM_PROGRAM
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program in ("vscode", "cursor"):
        logger.debug(f"VSCode detected via TERM_PROGRAM={term_program}")
        return True

    # Check VSCode-specific env vars
    if os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_CWD"):
        logger.debug("VSCode detected via VSCODE_PID/VSCODE_CWD env var")
        return True

    # Check port file
    from .ide_bridge import SIDESHELL_DIR

    port_file = SIDESHELL_DIR / "vscode-port"
    if port_file.exists():
        logger.debug("VSCode detected via port file")
        return True

    # Check if code binary exists
    if shutil.which("code") or shutil.which("cursor"):
        logger.debug("VSCode/Cursor binary found in PATH")
        return True

    return False


def detect_intellij() -> bool:
    """Check if a JetBrains IDE is available.

    Detection methods:
    1. Check TERMINAL_EMULATOR env var
    2. Check JETBRAINS_IDE env var
    3. Check port file (~/.sideshell/intellij-port)
    """
    # JetBrains terminal sets TERMINAL_EMULATOR
    if "JetBrains" in os.environ.get("TERMINAL_EMULATOR", ""):
        logger.debug("IntelliJ detected via TERMINAL_EMULATOR env var")
        return True

    if os.environ.get("JETBRAINS_IDE"):
        logger.debug("IntelliJ detected via JETBRAINS_IDE env var")
        return True

    # Check port file
    from .ide_bridge import SIDESHELL_DIR

    port_file = SIDESHELL_DIR / "intellij-port"
    if port_file.exists():
        logger.debug("IntelliJ detected via port file")
        return True

    return False


def detect_iterm2() -> bool:
    """Check if iTerm2 is available.

    Detection methods:
    1. Check TERM_PROGRAM env var
    2. Check if iTerm2.app exists
    3. Check if iterm2 Python package is importable
    """
    # Check environment variable
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program == "iTerm.app":
        logger.debug("iTerm2 detected via TERM_PROGRAM")
        return True

    # Check if running inside iTerm2 (LC_TERMINAL)
    lc_terminal = os.environ.get("LC_TERMINAL", "")
    if lc_terminal == "iTerm2":
        logger.debug("iTerm2 detected via LC_TERMINAL")
        return True

    # Check ITERM_SESSION_ID
    if os.environ.get("ITERM_SESSION_ID"):
        logger.debug("iTerm2 detected via ITERM_SESSION_ID")
        return True

    # Check if iTerm2.app exists
    iterm_paths = [
        "/Applications/iTerm.app",
        os.path.expanduser("~/Applications/iTerm.app"),
    ]
    for path in iterm_paths:
        if os.path.exists(path):
            logger.debug(f"iTerm2 detected at {path}")
            return True

    # Check if iterm2 module is available
    try:
        import iterm2  # noqa: F401

        logger.debug("iTerm2 Python module available")
        return True
    except ImportError:
        pass

    return False


def detect_tmux() -> bool:
    """Check if tmux is available.

    Detection methods:
    1. Check TMUX env var (inside tmux session)
    2. Check if tmux binary exists
    """
    # Check if inside tmux session
    if os.environ.get("TMUX"):
        logger.debug("tmux detected via TMUX env var")
        return True

    # Check if tmux binary exists
    if shutil.which("tmux"):
        logger.debug("tmux binary found in PATH")
        return True

    return False


def detect_wezterm() -> bool:
    """Check if WezTerm is available.

    Detection methods:
    1. Check WEZTERM_PANE env var (inside WezTerm)
    2. Check TERM_PROGRAM env var
    3. Check if wezterm binary exists
    """
    # Check if inside WezTerm
    if os.environ.get("WEZTERM_PANE"):
        logger.debug("WezTerm detected via WEZTERM_PANE env var")
        return True

    # Check TERM_PROGRAM
    if os.environ.get("TERM_PROGRAM") == "WezTerm":
        logger.debug("WezTerm detected via TERM_PROGRAM")
        return True

    # Check if wezterm binary exists
    if shutil.which("wezterm"):
        logger.debug("wezterm binary found in PATH")
        return True

    return False


def detect_kitty() -> bool:
    """Check if Kitty is available.

    Detection methods:
    1. Check KITTY_WINDOW_ID env var (inside Kitty)
    2. Check TERM env var for xterm-kitty
    3. Check if kitten or kitty binary exists
    """
    # Check if inside Kitty
    if os.environ.get("KITTY_WINDOW_ID"):
        logger.debug("Kitty detected via KITTY_WINDOW_ID env var")
        return True

    # Check TERM
    if os.environ.get("TERM") == "xterm-kitty":
        logger.debug("Kitty detected via TERM=xterm-kitty")
        return True

    # Check if kitten or kitty binary exists
    if shutil.which("kitten") or shutil.which("kitty"):
        logger.debug("kitten/kitty binary found in PATH")
        return True

    return False


def detect_maquake() -> bool:
    """Check if maquake is available.

    Detection methods:
    1. Check if /tmp/maquake.sock exists
    """
    if os.path.exists("/tmp/maquake.sock"):
        logger.debug("maquake detected via socket file")
        return True

    return False


def detect_windows_terminal() -> bool:
    """Check if Windows Terminal is available.

    Detection methods:
    1. Check WT_SESSION env var (inside Windows Terminal)
    2. Check if wt.exe exists (Windows only)
    """
    import platform

    # Check if inside Windows Terminal
    if os.environ.get("WT_SESSION"):
        logger.debug("Windows Terminal detected via WT_SESSION env var")
        return True

    # Windows only checks
    if platform.system() == "Windows":
        # Check if wt.exe is in PATH
        if shutil.which("wt"):
            logger.debug("Windows Terminal (wt.exe) found in PATH")
            return True

        # Check common installation paths
        wt_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe"),
            os.path.expandvars(r"%ProgramFiles%\WindowsApps\Microsoft.WindowsTerminal_*\wt.exe"),
        ]
        for path in wt_paths:
            # Handle wildcards
            if "*" in path:
                import glob

                matches = glob.glob(path)
                if matches:
                    logger.debug(f"Windows Terminal found at {matches[0]}")
                    return True
            elif os.path.exists(path):
                logger.debug(f"Windows Terminal found at {path}")
                return True

    return False


def detect_backend() -> BackendType:
    """Auto-detect the best available backend.

    Priority:
    1. Parent process tree (who spawned the MCP server?)
    2. Environment variables (TERM_PROGRAM, ITERM_SESSION_ID, etc.)
    3. Port files (IDE extensions running)
    4. Available binaries
    5. Platform-based fallback

    Returns:
        BackendType enum value.
    """
    import platform

    # 1. Parent process detection (most accurate - knows who called us)
    parent_backend = detect_parent_process()
    if parent_backend:
        logger.info(f"Auto-detected backend via parent process: {parent_backend.value}")
        return parent_backend

    # 2. Environment-based detection (which terminal are we inside?)

    # Check if inside VSCode/Cursor integrated terminal
    if os.environ.get("VSCODE_PID") or os.environ.get("TERM_PROGRAM") in ("vscode", "cursor"):
        logger.info("Auto-detected backend: VSCode (running inside VSCode terminal)")
        return BackendType.VSCODE

    # Check if inside JetBrains IDE terminal
    if "JetBrains" in os.environ.get("TERMINAL_EMULATOR", ""):
        logger.info("Auto-detected backend: IntelliJ (running inside JetBrains terminal)")
        return BackendType.INTELLIJ

    # Check if inside iTerm2 (macOS)
    if platform.system() == "Darwin":
        term_program = os.environ.get("TERM_PROGRAM", "")
        if term_program == "iTerm.app" or os.environ.get("ITERM_SESSION_ID"):
            logger.info("Auto-detected backend: iTerm2 (running inside iTerm2)")
            return BackendType.ITERM2

    # Check if inside WezTerm
    if os.environ.get("WEZTERM_PANE") or os.environ.get("TERM_PROGRAM") == "WezTerm":
        logger.info("Auto-detected backend: WezTerm (running inside WezTerm)")
        return BackendType.WEZTERM

    # Check if inside Kitty
    if os.environ.get("KITTY_WINDOW_ID") or os.environ.get("TERM") == "xterm-kitty":
        logger.info("Auto-detected backend: Kitty (running inside Kitty)")
        return BackendType.KITTY

    # Check if inside Ghostty
    if os.environ.get("TERM_PROGRAM") == "ghostty" or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        logger.info("Auto-detected backend: Ghostty (running inside Ghostty)")
        return BackendType.GHOSTTY

    # Check if inside tmux
    if os.environ.get("TMUX"):
        logger.info("Auto-detected backend: tmux (running inside tmux)")
        return BackendType.TMUX

    # 3. Port file detection (IDE extension is running)
    from .ide_bridge import SIDESHELL_DIR

    if (SIDESHELL_DIR / "vscode-port").exists():
        logger.info("Auto-detected backend: VSCode (port file found)")
        return BackendType.VSCODE
    if (SIDESHELL_DIR / "intellij-port").exists():
        logger.info("Auto-detected backend: IntelliJ (port file found)")
        return BackendType.INTELLIJ

    # 4. Available backends by binary presence
    # On macOS, prefer iTerm2 if installed
    if platform.system() == "Darwin" and detect_iterm2():
        logger.info("Auto-detected backend: iTerm2")
        return BackendType.ITERM2

    # Check for WezTerm
    if detect_wezterm():
        logger.info("Auto-detected backend: WezTerm")
        return BackendType.WEZTERM

    # Check for Kitty
    if detect_kitty():
        logger.info("Auto-detected backend: Kitty")
        return BackendType.KITTY

    # Check for Ghostty
    if detect_ghostty():
        logger.info("Auto-detected backend: Ghostty")
        return BackendType.GHOSTTY

    # Check for maquake
    if detect_maquake():
        logger.info("Auto-detected backend: maquake")
        return BackendType.MAQUAKE

    # Check for tmux
    if detect_tmux():
        logger.info("Auto-detected backend: tmux")
        return BackendType.TMUX

    # 5. Fallback
    if platform.system() == "Darwin":
        logger.warning("No backend detected, falling back to iTerm2")
        return BackendType.ITERM2

    logger.warning("No backend detected, falling back to tmux")
    return BackendType.TMUX


def get_backend(backend_type: BackendType = BackendType.AUTO) -> TerminalBackend:
    """Get backend instance.

    Args:
        backend_type: Backend type to use. AUTO will auto-detect.

    Returns:
        TerminalBackend instance.

    Raises:
        ValueError: If requested backend is not available.
    """
    # Auto-detect if needed
    if backend_type == BackendType.AUTO:
        backend_type = detect_backend()

    if backend_type == BackendType.ITERM2:
        try:
            from .iterm2_backend import ITermBackend
        except ImportError:
            raise ValueError(
                "iTerm2 backend requires the iterm2 package. Install with: pip install sideshell-mcp[iterm2]"
            ) from None

        backend = ITermBackend()
        if not backend.is_available:
            raise ValueError(
                "iTerm2 backend requested but not available. "
                "Please install iTerm2 and enable Python API, or use --backend=tmux"
            )
        return backend

    elif backend_type == BackendType.TMUX:
        from .tmux_backend import TmuxBackend

        backend = TmuxBackend()
        if not backend.is_available:
            raise ValueError("tmux backend requested but not available. Please install tmux, or use --backend=iterm2")
        return backend

    elif backend_type == BackendType.WEZTERM:
        from .wezterm_backend import WezTermBackend

        backend = WezTermBackend()
        if not backend.is_available:
            raise ValueError(
                "WezTerm backend requested but not available. Please install WezTerm, or use --backend=tmux"
            )
        return backend

    elif backend_type == BackendType.KITTY:
        from .kitty_backend import KittyBackend

        backend = KittyBackend()
        if not backend.is_available:
            raise ValueError("Kitty backend requested but not available. Please install Kitty, or use --backend=tmux")
        return backend

    elif backend_type == BackendType.GHOSTTY:
        from .ghostty_tmux_backend import GhosttyTmuxBackend

        backend = GhosttyTmuxBackend()
        if backend.is_available:
            return backend
        raise ValueError(
            "ghostty_tmux backend requires Ghostty (1.3+) and tmux. Please install tmux: brew install tmux"
        )

    elif backend_type == BackendType.MAQUAKE:
        from .maquake_backend import MaQuakeBackend

        backend = MaQuakeBackend()
        if not backend.is_available:
            raise ValueError(
                "maquake backend requested but not available. maquake must be running (socket at /tmp/maquake.sock)"
            )
        return backend

    elif backend_type == BackendType.VSCODE:
        from .vscode_backend import VSCodeBackend

        return VSCodeBackend()

    elif backend_type == BackendType.INTELLIJ:
        from .intellij_backend import IntelliJBackend

        return IntelliJBackend()

    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


def list_available_backends() -> list[BackendType]:
    """List all available backends.

    Returns:
        List of available BackendType values.
    """
    available = []

    if detect_iterm2():
        available.append(BackendType.ITERM2)

    if detect_tmux():
        available.append(BackendType.TMUX)

    if detect_wezterm():
        available.append(BackendType.WEZTERM)

    if detect_kitty():
        available.append(BackendType.KITTY)

    if detect_ghostty():
        available.append(BackendType.GHOSTTY)

    if detect_maquake():
        available.append(BackendType.MAQUAKE)

    if detect_vscode():
        available.append(BackendType.VSCODE)

    if detect_intellij():
        available.append(BackendType.INTELLIJ)

    return available


def get_system_info() -> dict:
    """Get system and terminal detection info.

    Returns:
        Dictionary with platform info and detected terminals.
    """
    import platform

    system = platform.system()

    # Detect all terminals
    terminals = {
        "iterm2": detect_iterm2() if system == "Darwin" else False,
        "tmux": detect_tmux(),
        "wezterm": detect_wezterm(),
        "kitty": detect_kitty(),
        "ghostty": detect_ghostty(),
        "maquake": detect_maquake(),
        "vscode": detect_vscode(),
        "intellij": detect_intellij(),
        "windows_terminal": detect_windows_terminal() if system == "Windows" else False,
    }

    # Determine current terminal (running inside)
    # First try parent process detection
    parent = detect_parent_process()
    current = None
    if parent:
        name_map = {
            BackendType.ITERM2: "iTerm2",
            BackendType.TMUX: "tmux",
            BackendType.WEZTERM: "WezTerm",
            BackendType.KITTY: "Kitty",
            BackendType.GHOSTTY: "Ghostty",
            BackendType.MAQUAKE: "maquake",
            BackendType.VSCODE: "VS Code",
            BackendType.INTELLIJ: "JetBrains IDE",
        }
        current = name_map.get(parent)

    # Fallback to env var detection
    if not current:
        if os.environ.get("VSCODE_PID") or os.environ.get("TERM_PROGRAM") in ("vscode", "cursor"):
            current = "VS Code"
        elif "JetBrains" in os.environ.get("TERMINAL_EMULATOR", ""):
            current = "JetBrains IDE"
        elif os.environ.get("ITERM_SESSION_ID") or os.environ.get("TERM_PROGRAM") == "iTerm.app":
            current = "iTerm2"
        elif os.environ.get("WT_SESSION"):
            current = "Windows Terminal"
        elif os.environ.get("WEZTERM_PANE") or os.environ.get("TERM_PROGRAM") == "WezTerm":
            current = "WezTerm"
        elif os.environ.get("KITTY_WINDOW_ID"):
            current = "Kitty"
        elif os.environ.get("TERM_PROGRAM") == "ghostty" or os.environ.get("GHOSTTY_RESOURCES_DIR"):
            current = "Ghostty"
        elif os.environ.get("TMUX"):
            current = "tmux"

    return {
        "platform": system,
        "platform_release": platform.release(),
        "python_version": platform.python_version(),
        "current_terminal": current,
        "available_terminals": {k: v for k, v in terminals.items() if v},
        "all_terminals": terminals,
    }


def print_startup_info() -> str:
    """Print startup info about available backends.

    Returns:
        Formatted string with system info.
    """
    info = get_system_info()

    lines = [
        f"Platform: {info['platform']} {info['platform_release']}",
    ]

    if info["current_terminal"]:
        lines.append(f"Running inside: {info['current_terminal']}")

    available = list(info["available_terminals"].keys())
    if available:
        # Format nicely
        terminal_names = {
            "iterm2": "iTerm2",
            "tmux": "tmux",
            "wezterm": "WezTerm",
            "kitty": "Kitty",
            "ghostty": "Ghostty",
            "maquake": "maquake",
            "vscode": "VS Code",
            "intellij": "JetBrains IDE",
            "windows_terminal": "Windows Terminal",
        }
        names = [terminal_names.get(t, t) for t in available]
        lines.append(f"Available backends: {', '.join(names)}")
    else:
        lines.append("Available backends: none detected")

    return "\n".join(lines)
