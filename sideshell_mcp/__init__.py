"""vibe-sideshell - AI sidecar terminal for Claude/Cursor."""

__version__ = "1.0.0"

from .server import VibeSideshellServer, cli_main, main

__all__ = ["VibeSideshellServer", "cli_main", "main"]
