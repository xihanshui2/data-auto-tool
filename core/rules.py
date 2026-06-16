"""TOML rule persistence layer: load, save, delete, validate."""

from __future__ import annotations

import re
import tomllib
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomli_w

from core.models import Rule

_RULES_DIR = Path(__file__).parent.parent / "config" / "rules"
_RULES_DIR.mkdir(parents=True, exist_ok=True)

_CURRENT_VERSION = 1


def _slugify(name: str) -> str:
    """Convert a rule name to a safe filename slug.

    - Lowercase
    - Replace non-alphanumeric chars with underscores
    - Collapse consecutive underscores
    - Strip leading/trailing underscores
    """
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9一-鿿]+", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    slug = slug.strip("_")
    if not slug:
        slug = "rule"
    return slug


def load_rules(file_type: str | None = None) -> list[Rule]:
    """Load all valid rules from ``config/rules/*.toml``.

    Parameters
    ----------
    file_type:
        If given, only return rules whose ``file_type`` matches.

    Returns
    -------
    List of validated :class:`Rule` objects.

    Notes
    -----
    - Rules whose ``version`` does not match the current model version are
      skipped with a warning.
    - Files that fail TOML parsing are reported and skipped.
    """
    rules: list[Rule] = []
    for path in sorted(_RULES_DIR.glob("*.toml")):
        try:
            raw = path.read_text(encoding="utf-8")
            data: dict[str, Any] = tomllib.loads(raw)
        except tomllib.TOMLDecodeError as exc:
            warnings.warn(f"跳过损坏的 TOML 文件 {path.name}: {exc}")
            continue

        version = data.get("version", 1)
        if version != _CURRENT_VERSION:
            warnings.warn(
                f"跳过版本不匹配的规则 {path.name}: "
                f"文件版本={version}, 期望版本={_CURRENT_VERSION}"
            )
            continue

        try:
            rule = Rule.model_validate_from_toml(data)
        except Exception as exc:
            warnings.warn(f"跳过校验失败的规则 {path.name}: {exc}")
            continue

        if file_type is not None and rule.file_type != file_type:
            continue
        rules.append(rule)

    return rules


def save_rule(rule: Rule) -> None:
    """Serialize *rule* to TOML and write to ``config/rules/{slug}.toml``.

    The ``updated_at`` timestamp is refreshed before writing.
    """
    rule.updated_at = datetime.now(timezone.utc)
    data = rule.model_dump_for_toml()
    # tomli_w does not support None values; drop them.
    data = {k: v for k, v in data.items() if v is not None}
    path = _RULES_DIR / f"{_slugify(rule.name)}.toml"
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def delete_rule(name: str) -> None:
    """Delete the TOML file for the rule named *name*."""
    path = _RULES_DIR / f"{_slugify(name)}.toml"
    if path.exists():
        path.unlink()


def validate_rule_data(data: dict[str, Any]) -> Rule:
    """Validate a raw dict and return a :class:`Rule`.

    Raises
    ------
    pydantic.ValidationError
        If the data does not conform to the model.
    """
    return Rule.model_validate(data)
