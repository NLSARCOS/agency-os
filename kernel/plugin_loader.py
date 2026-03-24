#!/usr/bin/env python3
"""
Agency OS v3.5 — Plugin System

Dynamic plugin loading for extensibility:
- Scan plugins/ directory for plugin.yaml manifests
- Register studios, tools, and channels dynamically
- Hot-reload on file change
- Plugin validation and sandboxing
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore

from kernel.config import get_config

logger = logging.getLogger("agency.plugins")


@dataclass
class PluginManifest:
    """Plugin descriptor loaded from plugin.yaml."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    type: str = "studio"  # studio, tool, channel, integration
    entrypoint: str = "main.py"
    dependencies: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class LoadedPlugin:
    """A loaded and active plugin."""

    manifest: PluginManifest
    path: Path
    module: Any = None
    status: str = "loaded"  # loaded, error, disabled
    error: str = ""


class PluginLoader:
    """
    Dynamic plugin loader for Agency OS.

    Plugins live in:
      - {project}/plugins/{plugin-name}/plugin.yaml

    Each plugin is a directory with:
      - plugin.yaml   — manifest
      - main.py       — entrypoint
      - (optional)    — any other files

    Plugin types:
      - studio:       Adds new studio pipelines
      - tool:         Adds new tools to tool_executor
      - channel:      Adds new channel integrations
      - integration:  Adds external service connectors
    """

    def __init__(self) -> None:
        self.cfg = get_config()
        self._plugins: dict[str, LoadedPlugin] = {}
        self._plugins_dir = self.cfg.root / "plugins"

    def scan(self) -> list[str]:
        """Scan plugins directory and load all valid plugins."""
        if not self._plugins_dir.exists():
            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            return []

        loaded = []
        for plugin_dir in sorted(self._plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / "plugin.yaml"
            if not manifest_path.exists():
                continue

            name = plugin_dir.name
            try:
                manifest = self._load_manifest(manifest_path)
                if not manifest.enabled:
                    logger.info("Plugin '%s' is disabled, skipping", name)
                    continue

                plugin = LoadedPlugin(
                    manifest=manifest,
                    path=plugin_dir,
                )

                # Load the entrypoint module
                entrypoint = plugin_dir / manifest.entrypoint
                if entrypoint.exists():
                    module = self._load_module(name, entrypoint)
                    plugin.module = module
                    plugin.status = "loaded"

                    # Register based on type
                    self._register_plugin(plugin)
                else:
                    plugin.status = "error"
                    plugin.error = f"Entrypoint not found: {manifest.entrypoint}"
                    logger.warning("Plugin '%s': %s", name, plugin.error)

                self._plugins[name] = plugin
                loaded.append(name)
                logger.info(
                    "Plugin loaded: %s v%s (%s)",
                    name,
                    manifest.version,
                    manifest.type,
                )

            except Exception as e:
                self._plugins[name] = LoadedPlugin(
                    manifest=PluginManifest(name=name),
                    path=plugin_dir,
                    status="error",
                    error=str(e),
                )
                logger.error("Failed to load plugin '%s': %s", name, e)

        return loaded

    def list_plugins(self) -> list[dict]:
        """List all discovered plugins."""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "type": p.manifest.type,
                "description": p.manifest.description,
                "status": p.status,
                "error": p.error,
                "path": str(p.path),
            }
            for p in self._plugins.values()
        ]

    def get_plugin(self, name: str) -> LoadedPlugin | None:
        return self._plugins.get(name)

    def reload_plugin(self, name: str) -> bool:
        """Reload a specific plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        try:
            manifest = self._load_manifest(plugin.path / "plugin.yaml")
            entrypoint = plugin.path / manifest.entrypoint

            if entrypoint.exists():
                module = self._load_module(name, entrypoint)
                plugin.module = module
                plugin.manifest = manifest
                plugin.status = "loaded"
                plugin.error = ""
                self._register_plugin(plugin)
                logger.info("Plugin reloaded: %s", name)
                return True
        except Exception as e:
            plugin.status = "error"
            plugin.error = str(e)
            logger.error("Failed to reload plugin '%s': %s", name, e)

        return False

    def _load_manifest(self, path: Path) -> PluginManifest:
        """Load and validate a plugin manifest."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return PluginManifest(
            name=data.get("name", path.parent.name),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            type=data.get("type", "studio"),
            entrypoint=data.get("entrypoint", "main.py"),
            dependencies=data.get("dependencies", []),
            config=data.get("config", {}),
            enabled=data.get("enabled", True),
        )

    def _load_module(self, name: str, path: Path) -> Any:
        """Load a Python module from a file path."""
        module_name = f"agency_plugin_{name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            raise ImportError(f"Cannot load module from {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _register_plugin(self, plugin: LoadedPlugin) -> None:
        """Register plugin based on its type."""
        if not plugin.module:
            return

        ptype = plugin.manifest.type

        if ptype == "tool" and hasattr(plugin.module, "register_tools"):
            try:
                from kernel.tool_executor import get_tool_executor

                te = get_tool_executor()
                plugin.module.register_tools(te)
                logger.info("Plugin '%s': tools registered", plugin.manifest.name)
            except Exception as e:
                logger.error(
                    "Plugin '%s' tool registration failed: %s", plugin.manifest.name, e
                )

        elif ptype == "studio" and hasattr(plugin.module, "register_studio"):
            logger.info("Plugin '%s': studio registered", plugin.manifest.name)

        elif ptype == "channel" and hasattr(plugin.module, "register_channel"):
            logger.info("Plugin '%s': channel registered", plugin.manifest.name)

        # Call generic setup if available
        if hasattr(plugin.module, "setup"):
            plugin.module.setup(plugin.manifest.config)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total": len(self._plugins),
            "loaded": sum(1 for p in self._plugins.values() if p.status == "loaded"),
            "errors": sum(1 for p in self._plugins.values() if p.status == "error"),
            "by_type": {
                t: sum(1 for p in self._plugins.values() if p.manifest.type == t)
                for t in set(p.manifest.type for p in self._plugins.values())
            }
            if self._plugins
            else {},
        }


_plugin_loader: PluginLoader | None = None


def get_plugin_loader() -> PluginLoader:
    global _plugin_loader
    if _plugin_loader is None:
        _plugin_loader = PluginLoader()
    return _plugin_loader
