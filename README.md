# blender-mcp-nimble

A trimmed fork of [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp). Four MCP tools, no telemetry, no asset-marketplace bloat.

## What's different

Upstream blender-mcp ships 21 tools and a Supabase telemetry pipeline that pings on every tool call (and uploads viewport screenshots to a third-party bucket). For interactive iteration in a live Blender session, four primitives are enough:

| Tool | Purpose |
| --- | --- |
| `get_scene_info` | JSON dump of the current scene — objects, active object, render settings, frame range |
| `get_object_info` | JSON for a named object — transform, mesh stats, materials, modifiers |
| `get_viewport_screenshot` | PNG of the current 3D viewport |
| `execute_blender_code` | Arbitrary Python in the running Blender process; full `bpy` access |

Plus one MCP prompt — `construct_blender_strategy` — a short default strategy for working with these four tools.

### Removed from upstream

- **Asset marketplace tools** (17): PolyHaven (4), Sketchfab (4), Hyper3D Rodin (5), Hunyuan3D (4). `set_texture` is also gone — its Blender add-on handler is coupled to the PolyHaven download cache. For texture work, use `execute_blender_code` directly.
- **Telemetry**: the entire `telemetry.py` / `telemetry_decorator.py` / `config.py` stack, including the Supabase phone-home and the screenshot-upload path. `supabase` and `tomli` runtime deps are dropped.
- **`asset_creation_strategy()` prompt**: replaced with a marketplace-free variant.

Result: ~1,860 lines of upstream Python collapsed to ~270, with `mcp` as the only runtime dep.

## Install

```sh
git clone https://github.com/555n/blender-mcp-nimble.git
cd blender-mcp-nimble
pip install -e .
```

This installs a `blender-mcp-nimble` console script. The Python package is `blender_mcp_nimble` (distinct from upstream's `blender_mcp` so you can have both installed without shadowing).

### Blender side

This server still talks to the **upstream Blender add-on** (`addon.py` from [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)) — install that into Blender as the upstream README describes:

1. Download `addon.py` from the upstream repo.
2. In Blender: `Edit → Preferences → Add-ons → Install` → select `addon.py`. Enable it.
3. Open the 3D Viewport sidebar (press `N`), find the **BlenderMCP** tab, click **Connect to Claude**.

The add-on's extra PolyHaven/Sketchfab/Hyper3D/Hunyuan3D handlers are simply unused by this server. A future release of `blender-mcp-nimble` will likely strip the add-on too.

## MCP client config

### Claude Code

```jsonc
// .mcp.json (project) or ~/.claude.json (global)
{
  "mcpServers": {
    "blender-mcp": {
      "command": "blender-mcp-nimble",
      "args": []
    }
  }
}
```

### Claude Desktop / other MCP clients

Same shape — point the client at the `blender-mcp-nimble` binary; it speaks MCP over stdio.

## Why fork?

The upstream package is well-built and maintained, but two things made it a poor fit for our use case:

1. **Telemetry**: every tool call records to Supabase, every screenshot can be uploaded to a third-party bucket. Configurable, but on by default and not appropriate for our workflow.
2. **Tool count**: the marketplace tools occupy ~17 slots in the MCP tool list. In MCP clients that load tool definitions into the model's context window, this is non-trivial token cost. We rarely use the marketplaces — when we need an asset we have other paths.

## License

MIT. Original copyright Siddharth Ahuja (2025). Modifications copyright 555n (2026). See [LICENSE](LICENSE).

## Upstream

- Original project: https://github.com/ahujasid/blender-mcp
- Forked from: v1.5.5 (2026-05-07)
- Author of upstream: [@ahujasid](https://github.com/ahujasid)
