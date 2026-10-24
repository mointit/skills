"""Hermes plugin wrapper around the mattpocock/skills pack.

The upstream repo ships a Claude Code plugin manifest
(``.claude-plugin/plugin.json``) that Hermes does not read, so none of its
skills were loadable here. This module registers the pack's promoted skills
through ``ctx.register_skill`` so they resolve as ``skills:<name>``.

Two rules decide what gets registered:

* ``.claude-plugin/plugin.json`` is the upstream's own list of promoted
  skills — read it so the set tracks the repo instead of a copy here.
* Every registered skill keeps its own frontmatter ``name``; the
  ``skills:`` namespace comes from the plugin manifest, so a skill named
  ``grilling`` registers as ``skills:grilling`` and never shadows a
  same-named skill installed under ``~/.hermes/skills/``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("plugins.skills")

PLUGIN_ROOT = Path(__file__).resolve().parent
UPSTREAM_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"


def _promoted_skill_dirs() -> list[Path]:
    """Skill directories the upstream manifest promotes, in manifest order."""
    try:
        data = json.loads(UPSTREAM_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Skills plugin: cannot read %s (%s)", UPSTREAM_MANIFEST, exc)
        return []
    dirs: list[Path] = []
    for entry in data.get("skills", []):
        # Manifest paths are repo-relative and start with "./".
        path = (PLUGIN_ROOT / str(entry).lstrip("./")).resolve()
        try:
            path.relative_to(PLUGIN_ROOT)
        except ValueError:
            logger.warning("Skills plugin: skipping %r (escapes the plugin root)", entry)
            continue
        if not (path / "SKILL.md").is_file():
            logger.warning("Skills plugin: skipping %r (no SKILL.md)", entry)
            continue
        dirs.append(path)
    return dirs


def _frontmatter(skill_md: Path) -> dict:
    """The SKILL.md frontmatter as flat ``key: value`` pairs.

    Deliberately dependency-free: this repo ships to Claude Code and other
    harnesses too, and a YAML parser is not guaranteed to exist wherever the
    plugin runs. Skill frontmatter is flat scalars, so a line reader is
    enough — and it keeps this file free of private Hermes imports (a plugin
    may not reach into Hermes internals; see the catalog's public-surface
    rule).
    """
    try:
        text = skill_md.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line[:1].isspace():
            continue  # blank, comment, or a nested continuation
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def register(ctx) -> None:
    """Register every promoted skill under the plugin's namespace."""
    registered = 0
    for skill_dir in _promoted_skill_dirs():
        name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        frontmatter = _frontmatter(skill_md)
        description = str(frontmatter.get("description") or "").strip()
        try:
            ctx.register_skill(name, skill_md, description, frontmatter)
        except Exception as exc:  # one bad skill must not sink the whole pack
            logger.warning("Skills plugin: could not register %r (%s)", name, exc)
            continue
        registered += 1
    logger.info("Skills plugin: registered %d skill(s)", registered)
