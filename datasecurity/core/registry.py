from __future__ import annotations

import hashlib
import importlib.util
import io
import sys
import tokenize
from pathlib import Path

from .errors import ValidationError
from .plugin import Plugin, PluginSpec


class Registry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self.load_errors: list[str] = []
        self._loaded_paths: set[Path] = set()
        self.file_plugins: dict[Path, tuple[str, ...]] = {}
        self.file_errors: dict[Path, str] = {}
        self.file_sources: dict[Path, str] = {}

    def register(self, plugin: Plugin) -> None:
        if not isinstance(plugin, Plugin) or not isinstance(
            getattr(plugin, "spec", None), PluginSpec
        ):
            raise TypeError("插件必须继承 Plugin 并声明 PluginSpec")
        if plugin.spec.id in self._plugins:
            raise ValueError(f"插件 ID 重复：{plugin.spec.id}")
        self._plugins[plugin.spec.id] = plugin

    def get(self, plugin_id: str) -> Plugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise ValidationError(f"找不到插件：{plugin_id}") from exc

    def describe(self) -> list[dict]:
        return [self._plugins[key].spec.describe() for key in sorted(self._plugins)]

    def copy(self) -> Registry:
        """Stage a registry change without rerunning already trusted plugins."""
        result = Registry()
        result._plugins = dict(self._plugins)
        result._loaded_paths = set(self._loaded_paths)
        result.file_plugins = dict(self.file_plugins)
        result.file_errors = dict(self.file_errors)
        result.file_sources = dict(self.file_sources)
        result.load_errors = list(self.load_errors)
        return result

    def remove_file(self, path: Path) -> None:
        path = path.resolve()
        for plugin_id in self.file_plugins.pop(path, ()):
            self._plugins.pop(plugin_id, None)
        self._loaded_paths.discard(path)
        self.file_errors.pop(path, None)
        self.file_sources.pop(path, None)
        self.load_errors = list(self.file_errors.values())

    def load_file(self, path: Path, source: str | None = None) -> tuple[str, ...]:
        """Execute a trusted module and register the complete file atomically.

        compile() intentionally bypasses timestamp-based .pyc reuse: a same-size
        edit within a second must take effect when the user clicks reload.
        This is a loader, not a Python sandbox.
        """
        path = path.resolve()
        module_name = "_datasecurity_plugin_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        previous = sys.modules.get(module_name)
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError("无法创建模块加载器")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            content = source if source is not None else path.read_bytes()
            code = compile(content, str(path), "exec")
            exec(code, module.__dict__)
            if (
                not isinstance(getattr(module, "PLUGINS", None), (list, tuple))
                or not module.PLUGINS
            ):
                raise ValueError("模块必须声明非空 PLUGINS = [插件类, ...]")
            instances = [plugin_type() for plugin_type in module.PLUGINS]
            staged = Registry()
            for plugin in instances:
                staged.register(plugin)
                if plugin.spec.id in self._plugins:
                    raise ValueError(f"插件 ID 重复：{plugin.spec.id}")
            for plugin in instances:
                self.register(plugin)
            ids = tuple(plugin.spec.id for plugin in instances)
            self.file_plugins[path] = ids
            if isinstance(content, bytes):
                encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
                content = content.decode(encoding)
            self.file_sources[path] = content
            self._loaded_paths.add(path)
            return ids
        except BaseException:
            # Also restore module bookkeeping after SystemExit/KeyboardInterrupt;
            # their handling belongs to the caller, not to discovery metadata.
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous
            raise

    def discover(self, directory: Path) -> None:
        directory = directory.resolve()
        if not directory.is_dir():
            self.load_errors.append(f"插件目录不存在：{directory}")
            return
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_") or path in self._loaded_paths:
                continue
            try:
                self.load_file(path)
            except (Exception, SystemExit) as exc:
                self._loaded_paths.add(path)
                message = f"{path.name}：{type(exc).__name__}: {exc}"
                self.file_errors[path] = message
                self.load_errors.append(message)
