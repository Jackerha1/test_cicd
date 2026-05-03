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
    """Probe each configured LLM provider (claude-cli-api + openai-api)."""
    from src.llm import LLMError, get_router
    router = get_router()
    out = {}
    for name, prov in router._providers.items():
        try:
            out[name] = asyncio.run(prov.health())
        except LLMError as exc:
            out[name] = {"provider": name, "error": str(exc)}
    console.print_json(data=out)


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


# =============================================================================
# Karpathy v2 commands: eval, cost, trifecta-audit, memory
# =============================================================================

@app.command("eval")
def eval_cmd(only_agent: str = typer.Option(None, "--agent", "-a",
                                            help="Run only cases for this agent."),
             only_target: str = typer.Option(None, "--target", "-t",
                                             help="Run only cases of this target type "
                                                  "(agent | policy_engine).")) -> None:
    """Run the eval harness against `evals/cases/*.yaml` and print pass/fail.

    Use `--target policy_engine` for the deterministic, free, sub-second
    policy-rule cases (no LLM required — safe in any CI without API keys).
    """
    from evals.harness import run_all_sync, write_report
    results = run_all_sync(only_agent=only_agent, only_target=only_target)
    if not results:
        console.print("[yellow]No eval cases found.[/]")
        return

    t = Table("case", "target", "status", "checks", "duration", "fail_msg")
    passed = 0
    for r in results:
        status = "[green]PASS[/]" if r.passed else "[red]FAIL[/]"
        if r.passed:
            passed += 1
        checks = f"{r.pass_count}/{r.pass_count + r.fail_count}"
        fail = (r.failures[0] if r.failures else (r.agent_error or ""))[:60]
        dur = f"{r.duration_s:.3f}s" if r.target == "policy_engine" else f"{r.duration_s:.1f}s"
        t.add_row(r.name, r.target, status, checks, dur, fail)
    console.print(t)
    console.print(f"\n[bold]{passed}/{len(results)} cases passed[/]")
    write_report(results, ROOT / "logs" / "eval_latest.json")
    if passed != len(results):
        sys.exit(2)


@app.command("cost")
def cost(pipeline_id: str) -> None:
    """Token / latency / USD breakdown for a pipeline run."""
    rows = audit.fetch_pipeline(pipeline_id)
    if not rows:
        console.print(f"[yellow]No audit rows for {pipeline_id}[/]")
        return

    # Totals from per-agent agent_done telemetry payloads.
    by_agent: dict[str, dict] = {}
    for r in rows:
        if r["action"] in {"agent_done", "agent_failed"} and r["payload"]:
            telem = (r["payload"].get("telemetry") or {})
            if not telem:
                continue
            cur = by_agent.setdefault(r["actor"], {"tokens_in": 0, "tokens_out": 0,
                                                    "cost_usd": 0.0, "duration_s": 0.0})
            cur["tokens_in"]  += telem.get("tokens_in", 0)
            cur["tokens_out"] += telem.get("tokens_out", 0)
            cur["cost_usd"]   += telem.get("cost_usd", 0.0)
            cur["duration_s"] += telem.get("duration_s", 0.0)

    if not by_agent:
        console.print(f"[yellow]No telemetry rows for {pipeline_id} (older run?).[/]")
        return

    t = Table("agent", "tokens_in", "tokens_out", "cost_usd", "duration_s")
    tot_in = tot_out = 0
    tot_cost = tot_dur = 0.0
    for agent, m in sorted(by_agent.items()):
        t.add_row(agent, str(m["tokens_in"]), str(m["tokens_out"]),
                  f"${m['cost_usd']:.5f}", f"{m['duration_s']:.2f}s")
        tot_in += m["tokens_in"]; tot_out += m["tokens_out"]
        tot_cost += m["cost_usd"]; tot_dur += m["duration_s"]
    t.add_row("[bold]TOTAL[/]", str(tot_in), str(tot_out),
              f"[bold]${tot_cost:.5f}[/]", f"[bold]{tot_dur:.2f}s[/]")
    console.print(t)
    console.print("[dim]Estimates from char-count heuristic; not provider-reported.[/]")


@app.command("trifecta-audit")
def trifecta_audit() -> None:
    """Static analysis of approval matrix vs the lethal-trifecta rule."""
    from src.audit.trifecta import audit_trifecta
    findings = audit_trifecta()
    t = Table("agent", "untrusted_input", "private_data", "exfiltrate", "legs", "lethal?")
    lethal_count = 0
    for f in findings:
        mark = "[red]LETHAL[/]" if f.lethal else ("[yellow]2/3[/]" if f.legs == 2 else "[green]ok[/]")
        if f.lethal:
            lethal_count += 1
        t.add_row(
            f.agent,
            "yes" if f.has_untrusted_input else "no",
            "yes" if f.has_private_data else "no",
            "yes" if f.can_exfiltrate else "no",
            str(f.legs),
            mark,
        )
    console.print(t)
    if lethal_count:
        console.print(f"[red bold]{lethal_count} lethal-trifecta agent(s) detected — refusing.[/]")
        sys.exit(2)
    console.print("[green]No lethal-trifecta agents.[/]")


@app.command("memory")
def memory_show(repo: str) -> None:
    """Show the per-repo learned memory injected into context."""
    from src.memory import store
    m = store.load(repo)
    if not m or list(m.keys()) == ["repo"]:
        console.print(f"[yellow]No memory for repo {repo!r} yet.[/]")
        return
    console.print_json(data=m)


@app.command("serve")
def serve(port: int = typer.Option(8000, "--port", "-p"),
          host: str = typer.Option("0.0.0.0", "--host", "-H")) -> None:
    """Run the production webhook server locally (Karpathy: dev = prod -1)."""
    import uvicorn
    uvicorn.run("src.server.webhook:app", host=host, port=port, reload=False)


@app.command("providers")
def providers() -> None:
    """Show the configured per-agent provider+model routing."""
    from src.llm.router import get_router
    router = get_router()
    routing = router.config.get("routing") or {}
    default = router.config.get("default") or {}
    t = Table("agent", "provider", "model", "source")
    for agent in sorted({"triage", "planner", "bug_fix", "test_writer",
                         "security_scan", "code_review", "documentation",
                         "validation", "deployment", "critic", "reflector"}):
        r = router.routing_for(agent)
        src = "per-agent" if agent in routing else "default"
        t.add_row(agent, r.provider, r.model or "(default)", src)
    console.print(t)
    console.print(f"\n[dim]default: {default}[/]")
    import os as _os
    if _os.getenv("AICICD_FORCE_PROVIDER"):
        console.print(f"[yellow]AICICD_FORCE_PROVIDER={_os.getenv('AICICD_FORCE_PROVIDER')} overrides per-agent routing[/]")
    if _os.getenv("AICICD_FORCE_MODEL"):
        console.print(f"[yellow]AICICD_FORCE_MODEL={_os.getenv('AICICD_FORCE_MODEL')} overrides per-agent model[/]")


@app.command("compare")
def compare(
    providers: str = typer.Option("claude,openai", "--providers", "-p",
                                   help="Comma-separated providers to compare."),
    only_agent: str = typer.Option(None, "--agent", "-a",
                                    help="Limit to eval cases for this agent."),
) -> None:
    """Run the eval harness against each provider and print a side-by-side matrix."""
    import os as _os
    from evals.harness import run_all_sync

    provs = [p.strip() for p in providers.split(",") if p.strip()]
    if not provs:
        console.print("[red]At least one provider required.[/]")
        raise typer.Exit(code=2)

    matrix: dict[str, list] = {}
    saved_force = _os.environ.get("AICICD_FORCE_PROVIDER")
    try:
        for p in provs:
            console.rule(f"Running evals on provider={p}")
            _os.environ["AICICD_FORCE_PROVIDER"] = p
            # Force a fresh router so the override is re-read.
            from src.llm import router as _r
            _r._singleton = None
            matrix[p] = run_all_sync(only_agent=only_agent)
    finally:
        if saved_force is None:
            _os.environ.pop("AICICD_FORCE_PROVIDER", None)
        else:
            _os.environ["AICICD_FORCE_PROVIDER"] = saved_force
        from src.llm import router as _r
        _r._singleton = None

    # Render: rows = case names, columns = providers.
    case_names = sorted({r.name for results in matrix.values() for r in results})
    cols = ["case"] + provs
    t = Table(*cols)
    for case in case_names:
        row = [case]
        for p in provs:
            r = next((x for x in matrix[p] if x.name == case), None)
            if r is None:
                row.append("[dim]n/a[/]")
            elif r.passed:
                row.append(f"[green]PASS[/] {r.duration_s:.1f}s")
            else:
                why = (r.failures[0] if r.failures else (r.agent_error or ""))[:40]
                row.append(f"[red]FAIL[/] {why}")
        t.add_row(*row)
    console.print(t)

    # Summary line per provider.
    for p in provs:
        results = matrix[p]
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        console.print(f"  {p:8s} {passed}/{total} passed")


@app.command("reflect")
def reflect(pipeline_id: str) -> None:
    """Print the Reflector Agent's root-cause for a (failed/blocked) run."""
    p = ROOT / "logs" / f"{pipeline_id}.json"
    if not p.exists():
        console.print(f"[yellow]No result file for {pipeline_id}[/]")
        return
    data = json.loads(p.read_text())
    refl = data.get("reflector")
    if not refl:
        console.print("[yellow]No reflector output (run probably succeeded).[/]")
        return
    console.print_json(data=refl)


if __name__ == "__main__":
    app()
