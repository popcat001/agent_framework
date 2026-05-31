import os
from pathlib import Path

WORKDIR = Path(os.getenv("AGENT_WORKDIR", Path.cwd()))
SKILLS_DIR = WORKDIR / "skills"
PROMPTS_DIR = WORKDIR / "prompts"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOLS_DIR = WORKDIR / "tools"

COMPACT_THRESHOLD = 50000
COMPACT_KEEP_RECENT = 3

# --- LLM output caps (per messages.create() call) ---
# Default per-call output cap. Set to Claude Sonnet 4.6's full output ceiling
# so chat turns and report narratives never truncate. Bills for actual emitted
# tokens, not the cap, so a high value here is free for the 99% of turns that
# don't approach it.
MAX_TOKENS = 64000
# Compaction emits a short summary; 2000 is plenty and prevents runaway summaries.
MAX_TOKENS_COMPACT = 2000

# --- User memory ---
USER_MEMORY_TOP_K = 15
USER_MEMORY_RECALL_DEFAULT_LIMIT = 100
USER_MEMORY_MAX_WRITES_PER_TURN = 5
USER_MEMORY_MAX_PER_USER = 500
