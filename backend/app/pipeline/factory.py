from app.agents.fixer import FixAgent
from app.agents.investigator import InvestigatorAgent
from app.agents.verifier import VerificationPlannerAgent
from app.config import get_settings
from app.llm.nebius import NebiusClient
from app.pipeline.runner import RepairPipeline
from app.sandbox.factory import get_sandbox


def build_pipeline(on_event=None, *, adversarial: bool = True) -> RepairPipeline:
    """Wire the real Nebius/Nemotron agents to the real sandbox. No fallbacks."""
    client = NebiusClient()
    sandbox = get_sandbox()
    return RepairPipeline(
        sandbox=sandbox,
        fixer=FixAgent(client),
        planner=VerificationPlannerAgent(client) if adversarial else None,
        investigator=InvestigatorAgent(client),
        max_iterations=get_settings().max_repair_iterations,
        model_info=lambda: client.usage.model_dump(),
        on_event=on_event,
    )
