import os

from anthropic import AnthropicFoundry
from dotenv import load_dotenv

from agent.memory import _MEMORY_GUIDANCE

load_dotenv(override=True)

# Claude API Configuration (via Azure AI Foundry)
client = AnthropicFoundry(
    api_key=os.getenv("ANTHROPIC_FOUNDRY_API_KEY"),
    resource=os.getenv("ANTHROPIC_FOUNDRY_RESOURCE"),
)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


# The guidance block surfaced in the cached system prefix on the web path only.
# ``_MEMORY_GUIDANCE`` is the canonical text (lives next to the provider that
# implements the behavior it describes); we derive the str.format-safe copy
# here by doubling every brace so literal ``{...}`` in the text is not
# interpreted as a template slot by ``template.format(...)`` below.
MEMORY_GUIDANCE = _MEMORY_GUIDANCE.replace("{", "{{").replace("}", "}}")


# --- Prompts ---
def system_prompt(
    skill_descriptions: str,
    memory_tool_available: bool = False,
    template_path=None,
) -> str:
    """Render the agent's system prompt template.

    By default reads ``prompts/system.md`` (under the project ``PROMPTS_DIR``).
    Pass ``template_path`` (a ``Path``) to override — used by per-agent
    configs that ship their own ``system.md``. The template has three
    placeholders: ``{workdir}``, ``{skill_descriptions}``, ``{memory_guidance}``.
    """
    from pathlib import Path
    from agent.constants import WORKDIR, PROMPTS_DIR
    path = Path(template_path) if template_path is not None else (PROMPTS_DIR / "system.md")
    template = path.read_text()
    return template.format(
        workdir=WORKDIR,
        skill_descriptions=skill_descriptions,
        memory_guidance=MEMORY_GUIDANCE if memory_tool_available else "",
    )
