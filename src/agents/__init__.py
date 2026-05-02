"""Specialist agents. Each one is a thin wrapper around BaseAgent."""
from src.agents.base import AgentResult, BaseAgent
from src.agents.bug_fix import BugFixAgent
from src.agents.code_review import CodeReviewAgent
from src.agents.critic import CriticAgent
from src.agents.deployment import DeploymentAgent
from src.agents.documentation import DocumentationAgent
from src.agents.planner import PlannerAgent
from src.agents.reflector import ReflectorAgent
from src.agents.security_scan import SecurityScanAgent
from src.agents.test_writer import TestWriterAgent
from src.agents.triage import TriageAgent
from src.agents.validation import ValidationAgent

# Critic isn't in REGISTRY because it's parameterized (target_agent).
# Reflector isn't in REGISTRY because it's spawned post-hoc by the orchestrator.
REGISTRY = {
    "triage":        TriageAgent,
    "planner":       PlannerAgent,
    "bug_fix":       BugFixAgent,
    "test_writer":   TestWriterAgent,
    "security_scan": SecurityScanAgent,
    "code_review":   CodeReviewAgent,
    "documentation": DocumentationAgent,
    "validation":    ValidationAgent,
    "deployment":    DeploymentAgent,
}

__all__ = [
    "AgentResult", "BaseAgent", "REGISTRY",
    "TriageAgent", "PlannerAgent", "BugFixAgent", "TestWriterAgent",
    "SecurityScanAgent", "CodeReviewAgent", "DocumentationAgent",
    "ValidationAgent", "DeploymentAgent",
    "CriticAgent", "ReflectorAgent",
]
