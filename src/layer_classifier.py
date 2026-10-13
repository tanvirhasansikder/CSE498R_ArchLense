"""ArchLens layer classifier (Phase 3).

Assigns each project class to an architectural layer using only explicit,
documented configuration. There is no guessing from class names:

  1. classes  - a manual mapping {fully qualified class name: layer}; wins first
  2. layers   - package prefixes per layer; the longest matching prefix wins,
                so "repository.jdbc" beats "repository"

A class that matches nothing is "unclassified". It is reported, and rules are
not evaluated on edges that touch it, so an unknown layer never becomes a
false finding or a silent pass.
"""
from __future__ import annotations

from dataclasses import dataclass

UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Classification:
    layer: str
    matched_by: str        # "class_mapping" | "package_prefix" | "none"
    matched_value: str | None


class LayerClassifier:
    def __init__(self, config: dict) -> None:
        self.layer_names = [layer["name"] for layer in config.get("layers", [])]
        if len(set(self.layer_names)) != len(self.layer_names):
            raise ValueError("Duplicate layer names in rule configuration")
        self.prefixes: list[tuple[str, str]] = []
        seen: dict[str, str] = {}
        for layer in config.get("layers", []):
            for pkg in layer.get("packages", []):
                if pkg in seen:
                    raise ValueError(f"Package {pkg!r} is mapped to both "
                                     f"{seen[pkg]!r} and {layer['name']!r}")
                seen[pkg] = layer["name"]
                self.prefixes.append((pkg, layer["name"]))
        # Longest prefix first, so the most specific package wins.
        self.prefixes.sort(key=lambda p: len(p[0]), reverse=True)
        self.class_map: dict[str, str] = dict(config.get("classes", {}))
        for cls, layer in self.class_map.items():
            if layer not in self.layer_names:
                raise ValueError(f"Class {cls!r} is mapped to unknown layer {layer!r}")

    def classify(self, fqn: str) -> Classification:
        # Exact class, or a nested class inside a mapped class (Outer.Inner).
        for cls, layer in self.class_map.items():
            if fqn == cls or fqn.startswith(cls + "."):
                return Classification(layer, "class_mapping", cls)
        for pkg, layer in self.prefixes:
            if fqn.startswith(pkg + "."):
                return Classification(layer, "package_prefix", pkg)
        return Classification(UNCLASSIFIED, "none", None)

    def classify_all(self, fqns) -> dict[str, Classification]:
        return {f: self.classify(f) for f in sorted(fqns)}
