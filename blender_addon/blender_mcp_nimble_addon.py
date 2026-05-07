# blender-mcp-nimble — Blender add-on
#
# Trimmed fork of ahujasid/blender-mcp addon.py.
# Original (c) 2025 Siddharth Ahuja. Modifications (c) 2026 555n. MIT.
#
# Changes vs upstream:
# - Drops all asset-marketplace handlers (PolyHaven / Sketchfab / Hyper3D Rodin / Hunyuan3D)
# - Drops the hardcoded RODIN_FREE_TRIAL_KEY
# - Drops telemetry consent UI and the get_telemetry_consent handler
# - Drops the requests dep (only used by marketplaces)
# - Keeps: TCP socket server on 9876, the four core handlers, the Connect/Disconnect operators

import bpy
import mathutils
import json
import threading
import socket
import time
import traceback
import io
from contextlib import redirect_stdout

bl_info = {
    "name": "Blender MCP (nimble)",
    "author": "555n (forked from ahujasid/blender-mcp)",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlenderMCP",
    "description": "Trimmed MCP bridge — 4 core tools, no telemetry, no marketplace.",
    "category": "Interface",
}


class BlenderMCPServer:
    def __init__(self, host="localhost", port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None

    def start(self):
        if self.running:
            print("Server is already running")
            return
        self.running = True
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()
            print(f"BlenderMCP-nimble server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {e}")
            self.stop()

    def stop(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except Exception:
                pass
            self.server_thread = None
        print("BlenderMCP-nimble server stopped")

    def _server_loop(self):
        print("Server thread started")
        self.socket.settimeout(1.0)
        while self.running:
            try:
                try:
                    client, address = self.socket.accept()
                    print(f"Connected to client: {address}")
                    client_thread = threading.Thread(target=self._handle_client, args=(client,))
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Error accepting connection: {e}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in server loop: {e}")
                if not self.running:
                    break
                time.sleep(0.5)
        print("Server thread stopped")

    def _handle_client(self, client):
        print("Client handler started")
        client.settimeout(None)
        buffer = b""
        try:
            while self.running:
                try:
                    data = client.recv(8192)
                    if not data:
                        print("Client disconnected")
                        break
                    buffer += data
                    try:
                        command = json.loads(buffer.decode("utf-8"))
                        buffer = b""

                        def execute_wrapper():
                            try:
                                response = self.execute_command(command)
                                response_json = json.dumps(response)
                                try:
                                    client.sendall(response_json.encode("utf-8"))
                                except Exception:
                                    print("Failed to send response - client disconnected")
                            except Exception as e:
                                print(f"Error executing command: {e}")
                                traceback.print_exc()
                                try:
                                    error_response = {"status": "error", "message": str(e)}
                                    client.sendall(json.dumps(error_response).encode("utf-8"))
                                except Exception:
                                    pass
                            return None

                        bpy.app.timers.register(execute_wrapper, first_interval=0.0)
                    except json.JSONDecodeError:
                        pass
                except Exception as e:
                    print(f"Error receiving data: {e}")
                    break
        except Exception as e:
            print(f"Error in client handler: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass
            print("Client handler stopped")

    def execute_command(self, command):
        try:
            return self._execute_command_internal(command)
        except Exception as e:
            print(f"Error executing command: {e}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _execute_command_internal(self, command):
        cmd_type = command.get("type")
        params = command.get("params", {})

        handlers = {
            "get_scene_info": self.get_scene_info,
            "get_object_info": self.get_object_info,
            "get_viewport_screenshot": self.get_viewport_screenshot,
            "execute_code": self.execute_code,
        }

        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"Executing handler for {cmd_type}")
                result = handler(**params)
                return {"status": "success", "result": result}
            except Exception as e:
                print(f"Error in handler: {e}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": f"Unknown command type: {cmd_type}"}

    def get_scene_info(self):
        try:
            scene_info = {
                "name": bpy.context.scene.name,
                "object_count": len(bpy.context.scene.objects),
                "objects": [],
                "materials_count": len(bpy.data.materials),
            }
            for i, obj in enumerate(bpy.context.scene.objects):
                if i >= 10:
                    break
                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    "location": [
                        round(float(obj.location.x), 2),
                        round(float(obj.location.y), 2),
                        round(float(obj.location.z), 2),
                    ],
                }
                scene_info["objects"].append(obj_info)
            return scene_info
        except Exception as e:
            print(f"Error in get_scene_info: {e}")
            traceback.print_exc()
            return {"error": str(e)}

    @staticmethod
    def _get_aabb(obj):
        """World-space axis-aligned bounding box for a mesh object."""
        if obj.type != "MESH":
            raise TypeError("Object must be a mesh")
        local_bbox_corners = [mathutils.Vector(corner) for corner in obj.bound_box]
        world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]
        min_corner = mathutils.Vector(map(min, zip(*world_bbox_corners)))
        max_corner = mathutils.Vector(map(max, zip(*world_bbox_corners)))
        return [[*min_corner], [*max_corner]]

    def get_object_info(self, name):
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
            "materials": [],
        }
        if obj.type == "MESH":
            obj_info["world_bounding_box"] = self._get_aabb(obj)
        for slot in obj.material_slots:
            if slot.material:
                obj_info["materials"].append(slot.material.name)
        if obj.type == "MESH" and obj.data:
            mesh = obj.data
            obj_info["mesh"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "polygons": len(mesh.polygons),
            }
        return obj_info

    def get_viewport_screenshot(self, max_size=800, filepath=None, format="png"):
        try:
            if not filepath:
                return {"error": "No filepath provided"}
            area = None
            for a in bpy.context.screen.areas:
                if a.type == "VIEW_3D":
                    area = a
                    break
            if not area:
                return {"error": "No 3D viewport found"}
            with bpy.context.temp_override(area=area):
                bpy.ops.screen.screenshot_area(filepath=filepath)
            img = bpy.data.images.load(filepath)
            width, height = img.size
            if max(width, height) > max_size:
                scale = max_size / max(width, height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img.scale(new_width, new_height)
                img.file_format = format.upper()
                img.save()
                width, height = new_width, new_height
            bpy.data.images.remove(img)
            return {"success": True, "width": width, "height": height, "filepath": filepath}
        except Exception as e:
            return {"error": str(e)}

    def execute_code(self, code):
        try:
            namespace = {"bpy": bpy}
            capture_buffer = io.StringIO()
            with redirect_stdout(capture_buffer):
                exec(code, namespace)
            return {"executed": True, "result": capture_buffer.getvalue()}
        except Exception as e:
            raise Exception(f"Code execution error: {e}")


class BLENDERMCP_PT_Panel(bpy.types.Panel):
    bl_label = "Blender MCP (nimble)"
    bl_idname = "BLENDERMCP_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlenderMCP"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "blendermcp_port")
        if not scene.blendermcp_server_running:
            layout.operator("blendermcp.start_server", text="Connect to Claude")
        else:
            layout.operator("blendermcp.stop_server", text="Disconnect")
            layout.label(text=f"Running on port {scene.blendermcp_port}")


class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to Claude"
    bl_description = "Start the BlenderMCP-nimble server to accept MCP client connections"

    def execute(self, context):
        scene = context.scene
        if not hasattr(bpy.types, "blendermcp_server") or not bpy.types.blendermcp_server:
            bpy.types.blendermcp_server = BlenderMCPServer(port=scene.blendermcp_port)
        bpy.types.blendermcp_server.start()
        scene.blendermcp_server_running = True
        return {"FINISHED"}


class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Disconnect"
    bl_description = "Stop the BlenderMCP-nimble server"

    def execute(self, context):
        scene = context.scene
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
            bpy.types.blendermcp_server.stop()
            del bpy.types.blendermcp_server
        scene.blendermcp_server_running = False
        return {"FINISHED"}


def register():
    bpy.types.Scene.blendermcp_port = bpy.props.IntProperty(
        name="Port",
        description="Port for the BlenderMCP-nimble server",
        default=9876,
        min=1024,
        max=65535,
    )
    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(
        name="Server Running",
        default=False,
    )
    bpy.utils.register_class(BLENDERMCP_PT_Panel)
    bpy.utils.register_class(BLENDERMCP_OT_StartServer)
    bpy.utils.register_class(BLENDERMCP_OT_StopServer)
    print("BlenderMCP-nimble addon registered")


def unregister():
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
        bpy.types.blendermcp_server.stop()
        del bpy.types.blendermcp_server
    bpy.utils.unregister_class(BLENDERMCP_PT_Panel)
    bpy.utils.unregister_class(BLENDERMCP_OT_StartServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_StopServer)
    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
    print("BlenderMCP-nimble addon unregistered")


if __name__ == "__main__":
    register()
