import sys
from collections.abc import Callable
from importlib import import_module
from typing import Any

import psutil

from elsewise.accessibility.contracts import (
    AccessibilityBackend,
    AccessibilityHealth,
    AccessibilityNode,
    AccessibilityProcess,
)


def _processes() -> tuple[AccessibilityProcess, ...]:
    result: list[AccessibilityProcess] = []
    for process in psutil.process_iter(("pid", "name")):
        try:
            name = str(process.info.get("name") or "").strip()
            if name:
                result.append(AccessibilityProcess(pid=int(process.info["pid"]), name=name[:256]))
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return tuple(sorted(result, key=lambda item: (item.name.casefold(), item.pid)))


class UnsupportedAccessibilityBackend:
    id = "unsupported"

    def health(self) -> AccessibilityHealth:
        return AccessibilityHealth("unavailable", self.id, "unsupported_platform")

    def processes(self) -> tuple[AccessibilityProcess, ...]:
        return _processes()

    def snapshot(self, pid: int, *, max_depth: int, max_nodes: int) -> AccessibilityNode:
        del pid, max_depth, max_nodes
        raise RuntimeError("unsupported_platform")


class MacOSAccessibilityBackend:
    id = "macos_ax"

    @staticmethod
    def _module() -> Any:
        try:
            return import_module("ApplicationServices")
        except ImportError as exc:
            raise RuntimeError("accessibility_runtime_missing") from exc

    def health(self) -> AccessibilityHealth:
        try:
            module = self._module()
        except RuntimeError as exc:
            return AccessibilityHealth("unavailable", self.id, str(exc))
        if not bool(module.AXIsProcessTrusted()):
            return AccessibilityHealth("permission_denied", self.id, "accessibility_permission")
        return AccessibilityHealth("available", self.id)

    def processes(self) -> tuple[AccessibilityProcess, ...]:
        return _processes()

    def snapshot(self, pid: int, *, max_depth: int, max_nodes: int) -> AccessibilityNode:
        module = self._module()
        if not bool(module.AXIsProcessTrusted()):
            raise RuntimeError("accessibility_permission")
        root = module.AXUIElementCreateApplication(pid)
        remaining = [max_nodes]

        def attribute(element: Any, name: str) -> Any:
            result = module.AXUIElementCopyAttributeValue(element, name, None)
            if isinstance(result, tuple) and len(result) == 2:
                error, value = result
                return value if int(error) == 0 else None
            return None

        def visit(element: Any, depth: int) -> AccessibilityNode:
            if remaining[0] <= 0:
                return AccessibilityNode(role="truncated")
            remaining[0] -= 1
            role = attribute(element, module.kAXRoleAttribute)
            name = attribute(element, module.kAXTitleAttribute)
            value = attribute(element, module.kAXValueAttribute)
            description = attribute(element, module.kAXDescriptionAttribute)
            children: tuple[AccessibilityNode, ...] = ()
            if depth < max_depth and remaining[0] > 0:
                raw_children = attribute(element, module.kAXChildrenAttribute) or ()
                children = tuple(visit(child, depth + 1) for child in tuple(raw_children))
            return AccessibilityNode(
                role=str(role or "unknown")[:128],
                name=str(name)[:1_024] if name is not None else None,
                value=str(value)[:1_024] if value is not None else None,
                description=str(description)[:1_024] if description is not None else None,
                children=children,
            )

        return visit(root, 0)


class LinuxAccessibilityBackend:
    id = "linux_atspi"

    @staticmethod
    def _module() -> Any:
        try:
            gi = import_module("gi")
            gi.require_version("Atspi", "2.0")
            return import_module("gi.repository.Atspi")
        except (ImportError, ValueError) as exc:
            raise RuntimeError("accessibility_runtime_missing") from exc

    def health(self) -> AccessibilityHealth:
        try:
            module = self._module()
            module.get_desktop(0)
        except (RuntimeError, Exception) as exc:
            code = str(exc) if isinstance(exc, RuntimeError) else "accessibility_unavailable"
            return AccessibilityHealth("unavailable", self.id, code)
        return AccessibilityHealth("available", self.id)

    def processes(self) -> tuple[AccessibilityProcess, ...]:
        return _processes()

    def snapshot(self, pid: int, *, max_depth: int, max_nodes: int) -> AccessibilityNode:
        module = self._module()
        desktop = module.get_desktop(0)
        remaining = [max_nodes]

        def child_count(node: Any) -> int:
            try:
                return int(node.get_child_count())
            except Exception:
                return 0

        def visit(node: Any, depth: int) -> AccessibilityNode:
            if remaining[0] <= 0:
                return AccessibilityNode(role="truncated")
            remaining[0] -= 1
            try:
                role = str(node.get_role_name() or "unknown")[:128]
            except Exception:
                role = "unknown"
            try:
                name = str(node.get_name() or "")[:1_024] or None
            except Exception:
                name = None
            children: list[AccessibilityNode] = []
            if depth < max_depth:
                for index in range(child_count(node)):
                    if remaining[0] <= 0:
                        break
                    try:
                        child = node.get_child_at_index(index)
                        if child is not None:
                            children.append(visit(child, depth + 1))
                    except Exception:
                        continue
            return AccessibilityNode(role=role, name=name, children=tuple(children))

        application = None
        for index in range(child_count(desktop)):
            candidate = desktop.get_child_at_index(index)
            try:
                candidate_pid = int(candidate.get_process_id())
            except Exception:
                continue
            if candidate_pid == pid:
                application = candidate
                break
        if application is None:
            raise RuntimeError("process_not_accessible")
        return visit(application, 0)


def accessibility_backend(
    platform: str | None = None,
) -> AccessibilityBackend:
    selected = platform or sys.platform
    factories: dict[str, Callable[[], AccessibilityBackend]] = {
        "darwin": MacOSAccessibilityBackend,
        "linux": LinuxAccessibilityBackend,
    }
    return factories.get(selected, UnsupportedAccessibilityBackend)()
