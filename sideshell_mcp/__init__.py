"""sideshell - AI sidecar terminal for Claude/Cursor."""

from .server import SideshellServer, VibeSideshellServer, cli_main, main

try:  # keep __version__ in lockstep with the installed distribution metadata
    from importlib.metadata import version

    __version__ = version("sideshell-mcp")
except Exception:  # not installed (e.g. running from a source checkout)
    __version__ = "0.0.0+dev"

__all__ = ["SideshellServer", "VibeSideshellServer", "__version__", "cli_main", "main"]
