"""blender-mcp-nimble — construct-native MCP bridge to a running Blender instance."""

__version__ = "0.1.0"

from .server import BlenderConnection, get_blender_connection

__all__ = ["BlenderConnection", "get_blender_connection"]
