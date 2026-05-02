"""CLI entry point for the AI CI/CD demo.

Subcommands:
  run <event.json>     run the full pipeline against a normalized event file
  health               check claude-cli-api connectivity
  audit <pipeline_id>  dump the audit log for a pipeline run
  list                 list example events you can feed into `run`
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.audit import log as audit
from src.claude_client import health_check
from src.config import ROOT
from src.orchestrator.pipeline import run_pipeline
from src.trigger.webhook import load_event

app = typer.Typer(add_completion=False, help="AI-Powered CI/CD demo")
console = Console()


@app.command("health")
def health() -> None:
    """Probe the claude-cli-api server (must be running on CLAUDE_CLI_API_URL)."""
    try:
        info = asyncio.run(health_check())
    except Exception as exc:
        console.print(f"[red]claude-cli-api unreachable:[/] {exc}")
        raise typer.Exit(code=1)
    console.print_json(data=info)


@app.command("list")
def list_examples() -> None:
    """List example event files in examples/."""
    examples = sorted((ROOT / "examples").glob("*.json"))
    if not examples:
        console.print("[yellow]No examples found in examples/[/]")
        return
    t = Table("file", "kind", "title")
    for e in examples:
        try:
            data = json.loads(e.read_text())
            t.add_row(e.name, data.get("kind", "?"), data.get("title", "")[:60])
        except Exception:
            t.add_row(e.name, "(unreadable)", "")
    console.print(t)


@app.command("run")
def run(event_file: str) -> None:
    """Run the pipeline against an event JSON file."""
    event = load_event(event_file)
    console.print(f"[cyan]Pipeline {event.pipeline_id}[/] — {event.kind}/{event.action} on {event.repo}")
    result = asyncio.run(run_pipeline(event))

    console.rule(f"Result: {result.final_status}  (flow={result.flow}, risk={result.risk_level})")
    console.print(result.summary or "(no summary)")
    console.print()
    console.print("[bold]Per-agent status:[/]")
    for name, ar in result.agent_results.items():
        mark = "[green]ok[/]" if ar.ok else "[red]FAIL[/]"
        retries = f" (retries={ar.retries})" if ar.retries else ""
        console.print(f"  - {name:14s} {mark}{retries}{('  err='+ar.error) if ar.error else ''}")

    if result.tool_calls:
        console.print()
        console.print("[bold]Tool calls:[/]")
        for tc in result.tool_calls:
            mark = "[green]ok[/]" if tc.get("ok") else "[red]denied[/]"
            console.print(f"  - {tc['action']:18s} {mark}  (decision={tc.get('decision')})")

    out_path = ROOT / "logs" / f"{event.pipeline_id}.json"
    out_path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
    console.print(f"\n[dim]Pipeline result written to {out_path}[/]")
    console.print(f"[dim]Inspect audit log:  ai-cicd audit {event.pipeline_id}[/]")
    if result.final_status not in ("approved", "needs_human"):
        sys.exit(2)


@app.command("audit")
def audit_dump(pipeline_id: str) -> None:
    """Print the immutable audit trail for a pipeline run."""
    rows = audit.fetch_pipeline(pipeline_id)
    if not rows:
        console.print(f"[yellow]No audit rows for pipeline_id={pipeline_id}[/]")
        return
    t = Table("ts", "actor", "action", "target", "risk", "decision")
    for r in rows:
        from datetime import datetime
        ts = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
        t.add_row(ts, r["actor"], r["action"], (r["target"] or "")[:32],
                  r["risk_level"] or "", r["decision"] or "")
    console.print(t)


if __name__ == "__main__":
    app()
