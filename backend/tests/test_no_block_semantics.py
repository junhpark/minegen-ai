"""Phase 18 acceptance guard (rule 127): active production code must not
consume BlockModel / SMU / ore-block concepts.

The scan is over CODE, not prose: identifiers (names, attributes, function /
class / argument names, imports) and non-docstring string literals (dict
keys, JSON field names). Docstrings and comments may describe the
prohibition or the migration history. The only string literals allowed to
mention legacy names are the explicit migration / legacy-detection paths
listed in ``ALLOWED_LITERALS``."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "minegen"

BANNED = (
    "BlockModel",
    "BlockModelConfig",
    "block_model",
    "blockModel",
    "RockType",
    "rock_type",
    "ore_flag",
    "ore_fraction",
    "oreFraction",
    "oreBlocks",
    "gradeBlocks",
    "blockGrid",
    "nBlocks",
    "nOreBlocks",
    "nAirBlocks",
    "nRockBlocks",
    "oreVolumeM3",
    "oreTonnes",
    "meanOreGrade",
    "faultCoreBlocks",
    "faultDamageBlocks",
    "SMU",
)

#: file → legacy names that may appear in STRING LITERALS there, because the
#: file implements the explicit v1→v2 migration or legacy-artifact detection
ALLOWED_LITERALS: dict[str, set[str]] = {
    "core/models.py": {"blockModel", "block_model"},
    "services/scenario_migration.py": {"blockModel", "block_model"},
    "world/spatial_fields.py": {"rock_type", "ore_fraction", "BlockModel"},
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _identifiers(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name):
            out.append((line, node.id))
        elif isinstance(node, ast.Attribute):
            out.append((line, node.attr))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.append((line, node.name))
        elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg is not None):
            out.append((line, node.arg))
        elif isinstance(node, ast.alias):
            out.append((line, node.name.split(".")[-1]))
            if node.asname:
                out.append((line, node.asname))
    return out


def _string_literals(tree: ast.AST) -> list[tuple[int, str]]:
    docs = _docstring_nodes(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
    ]


def _scan() -> list[str]:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, name in _identifiers(tree):
            if name in BANNED:
                offenders.append(f"{rel}:{line}: identifier {name}")
        allowed = ALLOWED_LITERALS.get(rel, set())
        for line, text in _string_literals(tree):
            for token in BANNED:
                if token in allowed:
                    continue
                if re.search(rf"\b{re.escape(token)}\b", text):
                    offenders.append(f"{rel}:{line}: literal {token!r} in {text!r}")
    return offenders


def test_no_block_semantics_in_active_backend_code() -> None:
    assert _scan() == [], "\n".join(_scan())


def test_legacy_literals_are_confined_to_migration_paths() -> None:
    """The allow-list must not rot: every allowed literal is still needed."""
    for rel, tokens in ALLOWED_LITERALS.items():
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        literals = " ".join(text for _, text in _string_literals(tree))
        for token in tokens:
            assert re.search(rf"\b{re.escape(token)}\b", literals), f"{rel}: {token} unused"
