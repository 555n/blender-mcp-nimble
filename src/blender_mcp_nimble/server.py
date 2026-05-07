"""
blender-mcp-nimble — construct-native MCP server for live Blender control.

Fork of ahujasid/blender-mcp v1.5.5. Drops:
- Telemetry (Supabase phone-home, screenshot upload, every-tool decoration)
- Polyhaven / Sketchfab / Hyper3D Rodin / Hunyuan3D asset marketplace tools (16 of 21)
- The asset_creation_strategy prompt that pushes marketplace usage
- supabase + tomli runtime deps

Keeps the four primitives that justify an interactive MCP bridge at all:
  get_scene_info, get_object_info, get_viewport_screenshot, execute_blender_code

Talks to the BlenderMCP Blender add-on over a TCP socket on port 9876
(addon's extra polyhaven/sketchfab/hyper3d/hunyuan3d handlers are ignored,
not removed — leaving the upstream add-on installable as-is for now).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict

from mcp.server.fastmcp import Context, FastMCP, Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("BlenderMCPNimble")

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876
SOCK_TIMEOUT = 180.0


@dataclass
class BlenderConnection:
    host: str
    port: int
    sock: socket.socket | None = None

    def connect(self) -> bool:
        if self.sock:
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Blender at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Blender: {e}")
            self.sock = None
            return False

    def disconnect(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Blender: {e}")
            finally:
                self.sock = None

    def receive_full_response(self, sock: socket.socket, buffer_size: int = 8192) -> bytes:
        chunks: list[bytes] = []
        sock.settimeout(SOCK_TIMEOUT)
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    chunks.append(chunk)
                    try:
                        data = b"".join(chunks)
                        json.loads(data.decode("utf-8"))
                        return data
                    except json.JSONDecodeError:
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {e}")
                    raise
        except socket.timeout:
            logger.warning("Socket timeout during chunked receive")
        except Exception as e:
            logger.error(f"Error during receive: {e}")
            raise

        if chunks:
            data = b"".join(chunks)
            try:
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Blender")
        command = {"type": command_type, "params": params or {}}
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            self.sock.sendall(json.dumps(command).encode("utf-8"))
            self.sock.settimeout(SOCK_TIMEOUT)
            response_data = self.receive_full_response(self.sock)
            response = json.loads(response_data.decode("utf-8"))
            if response.get("status") == "error":
                logger.error(f"Blender error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Blender"))
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Blender")
            self.sock = None
            raise Exception("Timeout waiting for Blender response - try simplifying your request")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {e}")
            self.sock = None
            raise Exception(f"Connection to Blender lost: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Blender: {e}")
            raise Exception(f"Invalid response from Blender: {e}")
        except Exception as e:
            logger.error(f"Error communicating with Blender: {e}")
            self.sock = None
            raise Exception(f"Communication error with Blender: {e}")


_blender_connection: BlenderConnection | None = None


def get_blender_connection() -> BlenderConnection:
    """Return cached connection, creating one if needed. Connection liveness
    is verified lazily — the next send_command will detect a dead socket and
    reset, and the call after that will reconnect. No upfront ping."""
    global _blender_connection
    if _blender_connection is not None and _blender_connection.sock is not None:
        return _blender_connection

    host = os.getenv("BLENDER_HOST", DEFAULT_HOST)
    port = int(os.getenv("BLENDER_PORT", DEFAULT_PORT))
    _blender_connection = BlenderConnection(host=host, port=port)
    if not _blender_connection.connect():
        _blender_connection = None
        raise Exception("Could not connect to Blender. Make sure the BlenderMCP add-on is running.")
    return _blender_connection


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    try:
        logger.info("blender-mcp-nimble starting up")
        try:
            get_blender_connection()
            logger.info("Connected to Blender on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Blender on startup: {e}")
            logger.warning("Open Blender, enable the BlenderMCP add-on, then click 'Connect to Claude' in the N-panel.")
        yield {}
    finally:
        global _blender_connection
        if _blender_connection:
            logger.info("Disconnecting from Blender on shutdown")
            _blender_connection.disconnect()
            _blender_connection = None
        logger.info("blender-mcp-nimble shut down")


mcp = FastMCP("BlenderMCP", lifespan=server_lifespan)


@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Return current Blender scene info as JSON: object list, active object, render settings, frame range."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_scene_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info: {e}")
        return f"Error getting scene info: {e}"


@mcp.tool()
def get_object_info(ctx: Context, object_name: str) -> str:
    """Return detailed info about a specific scene object as JSON: transform, mesh stats, materials, modifiers."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("get_object_info", {"name": object_name})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting object info: {e}")
        return f"Error getting object info: {e}"


@mcp.tool()
def get_viewport_screenshot(ctx: Context, max_size: int = 800) -> Image:
    """Capture a PNG screenshot of the current 3D viewport.

    Parameters:
    - max_size: Largest dimension in pixels (default 800).
    """
    try:
        blender = get_blender_connection()
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"blender_screenshot_{os.getpid()}.png")
        result = blender.send_command(
            "get_viewport_screenshot",
            {"max_size": max_size, "filepath": temp_path, "format": "png"},
        )
        if "error" in result:
            raise Exception(result["error"])
        if not os.path.exists(temp_path):
            raise Exception("Screenshot file was not created")
        with open(temp_path, "rb") as f:
            image_bytes = f.read()
        os.remove(temp_path)
        return Image(data=image_bytes, format="png")
    except Exception as e:
        logger.error(f"Error capturing screenshot: {e}")
        raise Exception(f"Screenshot failed: {e}")


@mcp.tool()
def execute_blender_code(ctx: Context, code: str) -> str:
    """Execute arbitrary Python in the running Blender instance. Full bpy access. Break large work into chunks."""
    try:
        blender = get_blender_connection()
        result = blender.send_command("execute_code", {"code": code})
        return f"Code executed successfully: {result.get('result', '')}"
    except Exception as e:
        logger.error(f"Error executing code: {e}")
        return f"Error executing code: {e}"


@mcp.prompt()
def construct_blender_strategy() -> str:
    """Construct-aware default strategy for live Blender work via blender-mcp-nimble."""
    return """Working in a live Blender session via blender-mcp-nimble.

Tools (4):
- get_scene_info — JSON of current scene state (call before/after structural changes)
- get_object_info — JSON for a single object (transform, mesh, materials, modifiers)
- get_viewport_screenshot — PNG of the current viewport (call before/after visible changes)
- execute_blender_code — arbitrary bpy Python in the running session

Defaults:
1. get_scene_info first if you don't already know the scene state.
2. For visible changes, screenshot before and after; verify the change matches intent.
3. Break large execute_blender_code calls into smaller chunks — easier to recover from a single bad block.
4. Prefer execute_blender_code with named, idempotent operators. Don't write code that depends on selection state being preserved across calls.
5. For repeatable / batch / headless work, hand off to blender-scripttool instead. This server is for interactive iteration only.

Output routing:
- Scratch files go to /tmp/555n/blender-op/
- Deliverables route via the operator's --output flag (caller decides). Never write deliverables inside the construct.
"""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
