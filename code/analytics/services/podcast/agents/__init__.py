"""Multi-agent podcast pipeline.

Top-down architecture: a producer agent plans the episode arc, per-scene
researchers gather focused data sequentially (each seeing prior scenes'
findings), per-scene writers produce one act each (each seeing the prior
writer's tail for clean hand-offs), and an editor smooths the junctions
between acts.

Coexists with the existing single-agent path in
`services.podcast.research_agent` + `services.podcast.script_generator`.
Selected via the ``PODCAST_PIPELINE`` env var; defaults to the single-agent
flow so existing deployments are unaffected.
"""

from .editor import edit_junctions
from .multi_agent_pipeline import run_multi_agent_pipeline
from .producer import plan_episode
from .scene_researcher import research_scene
from .scene_writer import write_scene

__all__ = [
    "edit_junctions",
    "plan_episode",
    "research_scene",
    "run_multi_agent_pipeline",
    "write_scene",
]
