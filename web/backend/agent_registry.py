"""Agent registry — discover per-agent configs from ``<project>/agents/*/agent.yaml``.

Each agent directory may contain:
  - ``agent.yaml`` (required): id, name, description, optional icon, optional default flag
  - ``system.md`` (optional): per-agent system prompt template; falls back to
    project-level ``prompts/system.md`` when missing
  - ``skills/`` (optional): per-agent skills (merged with shared ``<project>/skills/``)
  - ``tools/``  (optional): per-agent tools  (merged with shared ``<project>/tools/``)

The shared dirs come from the framework's ``agent.constants`` (``SKILLS_DIR``,
``TOOLS_DIR``), so cross-agent skills (e.g. ``charting``) and helper modules
(``utils.py``) stay in one place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from agent.constants import SKILLS_DIR as SHARED_SKILLS_DIR
from agent.constants import TOOLS_DIR as SHARED_TOOLS_DIR
from config import PROJECT_ROOT

logger = logging.getLogger(__name__)

AGENTS_ROOT = PROJECT_ROOT / "agents"


@dataclass
class AgentConfig:
    id: str
    name: str
    description: str
    icon: Optional[str]
    default: bool
    enabled: bool
    skill_dirs: list[Path]
    tool_dirs: list[Path]
    system_prompt_path: Optional[Path]
    # Optional list of {icon, text} dicts used by the WelcomeScreen. Empty
    # list means "fall back to the project-level default sampleQuestions".
    sample_questions: list[dict]

    def to_public_dict(self) -> dict:
        """Public payload returned by GET /agents (no filesystem paths)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "default": self.default,
            "sample_questions": self.sample_questions,
        }


_registry: dict[str, AgentConfig] | None = None
_default_id: Optional[str] = None
_ordered_ids: list[str] = []


def _discover() -> tuple[dict[str, AgentConfig], Optional[str], list[str]]:
    registry: dict[str, AgentConfig] = {}
    default_id: Optional[str] = None
    ordered: list[str] = []

    if not AGENTS_ROOT.exists():
        logger.info("agent_registry: no agents/ directory at %s", AGENTS_ROOT)
        return registry, default_id, ordered

    for agent_dir in sorted(AGENTS_ROOT.iterdir()):
        cfg_path = agent_dir / "agent.yaml"
        if not agent_dir.is_dir() or not cfg_path.exists():
            continue
        try:
            data = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception as e:
            logger.warning("agent_registry: skipping %s — %s", cfg_path, e)
            continue

        agent_id = data.get("id") or agent_dir.name
        skills_dir = agent_dir / "skills"
        tools_dir = agent_dir / "tools"
        # Convention: every agent dir must contain `system.md`. Falls back to
        # the project's legacy `prompts/system.md` if the agent doesn't ship
        # its own, which keeps single-agent setups working unchanged.
        sys_prompt_path = agent_dir / "system.md"
        if not sys_prompt_path.exists():
            sys_prompt_path = None

        # Sample questions are optional. Coerce each row to {icon, text}; drop
        # rows missing a `text` so a typo doesn't render an empty card.
        raw_qs = data.get("sample_questions") or []
        sample_questions: list[dict] = []
        for q in raw_qs:
            if isinstance(q, dict) and q.get("text"):
                sample_questions.append({
                    "icon": str(q.get("icon") or "HelpCircle"),
                    "text": str(q["text"]),
                })

        cfg = AgentConfig(
            id=agent_id,
            name=str(data.get("name", agent_id)),
            description=str(data.get("description", "")),
            icon=data.get("icon"),
            default=bool(data.get("default", False)),
            enabled=bool(data.get("enabled", True)),
            skill_dirs=[SHARED_SKILLS_DIR, skills_dir],
            tool_dirs=[SHARED_TOOLS_DIR, tools_dir],
            system_prompt_path=sys_prompt_path,
            sample_questions=sample_questions,
        )
        registry[agent_id] = cfg
        ordered.append(agent_id)
        if cfg.default and cfg.enabled and default_id is None:
            default_id = agent_id

    # Fall back to first enabled agent if no explicit default.
    if default_id is None:
        default_id = next((aid for aid in ordered if registry[aid].enabled), None)
    return registry, default_id, ordered


def _ensure_loaded() -> None:
    global _registry, _default_id, _ordered_ids
    if _registry is None:
        _registry, _default_id, _ordered_ids = _discover()
        logger.info(
            "agent_registry: loaded %d agents (default=%s)",
            len(_registry), _default_id,
        )


def list_agents() -> list[AgentConfig]:
    """All enabled agents, default first then config order. Disabled agents
    are hidden from the UI but remain resolvable by id via
    ``get_agent_config`` so existing conversations stay loadable."""
    _ensure_loaded()
    if not _ordered_ids:
        return []
    items = [_registry[i] for i in _ordered_ids if _registry[i].enabled]
    items.sort(key=lambda c: (not c.default, _ordered_ids.index(c.id)))
    return items


def get_agent_config(agent_id: Optional[str]) -> Optional[AgentConfig]:
    """Look up an agent by id; falls back to the default when ``agent_id`` is
    None or unknown. Returns None only if no agents are registered."""
    _ensure_loaded()
    if not _registry:
        return None
    if agent_id and agent_id in _registry:
        return _registry[agent_id]
    if _default_id:
        return _registry[_default_id]
    return None


def default_agent_id() -> Optional[str]:
    _ensure_loaded()
    return _default_id
