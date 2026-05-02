"""Sandbox.

In SANDBOX_MODE=subprocess we just run the command in a constrained shell
(no shell=True, scoped CWD, hard timeout). In SANDBOX_MODE=docker we'd shell
out to `docker run --rm --network=none ...`. The interface is identical so
the orchestrator doesn't have to care which mode is active.

The whole point: agents never get shell. The runner does, with limits.
"""
from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.audit import log as audit
from src.config import SANDBOX_MODE


@dataclass
class SandboxResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


async def run(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout_s: float = 60.0,
    pipeline_id: str = "n/a",
    label: str = "exec",
) -> SandboxResult:
    """Run a command list in the sandbox. NEVER pass `shell=True`-style strings."""
    if not cmd:
        raise ValueError("sandbox.run: cmd must not be empty")
    if SANDBOX_MODE == "docker":
        cmd = _wrap_docker(cmd, cwd)

    audit.log(
        pipeline_id=pipeline_id,
        actor="sandbox",
        action=f"exec:{label}",
        target=" ".join(shlex.quote(c) for c in cmd)[:300],
        decision="info",
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return SandboxResult(cmd=cmd, returncode=-1, stdout="", stderr="", timed_out=True)

    return SandboxResult(
        cmd=cmd,
        returncode=proc.returncode or 0,
        stdout=stdout_b.decode(errors="replace"),
        stderr=stderr_b.decode(errors="replace"),
    )


def _wrap_docker(cmd: list[str], cwd: Optional[Path]) -> list[str]:
    docker = ["docker", "run", "--rm", "--network=none", "--memory=512m", "--cpus=1.0"]
    if cwd:
        docker += ["-v", f"{cwd}:/work", "-w", "/work"]
    docker += ["python:3.11-slim"]
    docker += cmd
    return docker
