"""Build/Test Runner.

Executes the actual test command in the sandbox and returns a structured
result. The Code Review Agent and Validation Agent both consume this — they
are NOT allowed to take an agent's word that "tests pass." Real output, real
exit code, or it doesn't count.

For the MVP we run pytest if a tests/ dir exists. If neither pytest nor a
runtime is available (because the workspace is just a simulated patch),
we fall back to a "synthetic" pass record but mark `synthetic: true` so
Validation can refuse to approve based on it.
"""
from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from src.audit import log as audit
from src.sandbox import runner as sb


@dataclass
class TestRun:
    status: str                        # "pass" | "fail" | "error" | "skip"
    framework: str                     # "pytest" | "node" | "synthetic"
    returncode: int
    duration_s: float
    stdout_tail: str
    stderr_tail: str
    synthetic: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


async def run_tests(
    *,
    pipeline_id: str,
    workdir: Path,
    framework: Optional[str] = None,
    timeout_s: float = 120.0,
) -> TestRun:
    framework = framework or _detect(workdir)

    if framework == "synthetic":
        result = TestRun(
            status="pass",
            framework="synthetic",
            returncode=0,
            duration_s=0.0,
            stdout_tail="(no test runtime detected — synthetic pass; Validation must reject this)",
            stderr_tail="",
            synthetic=True,
        )
        audit.log(
            pipeline_id=pipeline_id,
            actor="runner",
            action="run_tests",
            decision="info",
            payload=result.to_dict(),
        )
        return result

    cmd = _build_cmd(framework)
    import time as _t
    t0 = _t.time()
    res = await sb.run(cmd, cwd=workdir, timeout_s=timeout_s,
                       pipeline_id=pipeline_id, label="run_tests")
    dur = _t.time() - t0

    status = "pass" if res.ok else ("error" if res.timed_out else "fail")
    out = TestRun(
        status=status,
        framework=framework,
        returncode=res.returncode,
        duration_s=dur,
        stdout_tail=res.stdout[-2000:],
        stderr_tail=res.stderr[-2000:],
    )
    audit.log(
        pipeline_id=pipeline_id,
        actor="runner",
        action="run_tests",
        decision="pass" if out.status == "pass" else "fail",
        payload=out.to_dict(),
    )
    return out


def _detect(workdir: Path) -> str:
    if (workdir / "tests").exists() and shutil.which("pytest"):
        return "pytest"
    if (workdir / "package.json").exists() and shutil.which("npm"):
        return "node"
    return "synthetic"


def _build_cmd(framework: str) -> list[str]:
    if framework == "pytest":
        return ["pytest", "-q", "--tb=short"]
    if framework == "node":
        return ["npm", "test", "--silent"]
    raise ValueError(f"unknown framework: {framework}")
