import re
from pathlib import Path
from typing import Iterable

from agent.constants import SKILLS_DIR


class SkillLoader:
    """Loads SKILL.md files from one or more directories.

    When multiple dirs are provided, later dirs override earlier ones on name
    collision (per-agent dirs win over shared). Backward-compatible: passing a
    single Path keeps the old behavior.
    """

    def __init__(self, skills_dir: Path | Iterable[Path] = SKILLS_DIR):
        if isinstance(skills_dir, (str, Path)):
            self.skills_dirs: list[Path] = [Path(skills_dir)]
        else:
            self.skills_dirs = [Path(d) for d in skills_dir]
        self.skills = {}
        self._load_all()

    def _load_all(self):
        for d in self.skills_dirs:
            if not d.exists():
                continue
            for f in sorted(d.rglob("SKILL.md")):
                text = f.read_text()
                meta, body = self._parse_frontmatter(text)
                name = meta.get("name", f.parent.name)
                # later dirs override earlier on collision
                self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
