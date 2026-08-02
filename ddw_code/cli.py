"""ddw-code CLI: parse args, build the loop, render output."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import load_config
from .context.detector import detect
from .providers import get_provider
from .security.permissions import PermissionManager
from .tools.builder import build_default_registry
from .tools.dispatcher import ToolDispatcher
from .turn_loop import TurnEvent, TurnLoop

console = Console()
err_console = Console(stderr=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ddw-code",
        description="Provider-agnostic CLI coding agent with token optimization.",
    )
    p.add_argument(
        "--print",
        dest="print_mode",
        action="store_true",
        help="Non-interactive mode: run once, print result, exit.",
    )
    p.add_argument(
        "--provider",
        choices=["minimax", "deepseek", "openai"],
        default="minimax",
        help="LLM provider (default: minimax).",
    )
    p.add_argument("--api-key", help="API key (or set MINIMAX_API_KEY).")
    p.add_argument("--base-url", help="Override the API base URL.")
    p.add_argument("--model", help="Override the model name.")
    p.add_argument("--max-turns", type=int, help="Max tool-call turns per request.")
    p.add_argument(
        "--workspace",
        type=Path,
        help="Working directory (default: current directory).",
    )
    p.add_argument(
        "--sandbox",
        action="store_true",
        help="Run with a conservative permission policy.",
    )
    p.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve mutating tools (bash, file_write, file_edit).",
    )
    p.add_argument(
        "--no-context",
        action="store_true",
        help="Skip loading project context files (AGENTS.md, README.md). Reduces token usage.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging to stderr."
    )
    p.add_argument(
        "prompt",
        nargs="?",
        help="User prompt. If omitted, the CLI enters interactive mode.",
    )
    return p


def _apply_sandbox(perm: PermissionManager) -> None:
    """Tighten the permission policy for sandbox mode."""
    from .security.permissions import Decision

    for name in ("bash", "file_write", "file_edit", "web_search"):
        perm.set_policy(name, Decision.FORCE_ASK)


async def run_loop(
    loop: TurnLoop,
    prompt: str,
    *,
    print_mode: bool,
    system_extra: str = "",
) -> tuple[str, int]:
    """Run a single turn and return (final_text, exit_code)."""
    final_text = ""
    last_event: TurnEvent | None = None
    with console.status("[bold green]ddw-code thinking...[/bold green]") if not print_mode else _NullCtx():
        async for ev in loop.run(prompt, system_extra=system_extra):
            last_event = ev
            if ev.kind == "text_delta":
                if print_mode:
                    console.print(ev.text, end="")
                final_text += ev.text
            elif ev.kind == "tool_call":
                if not print_mode:
                    console.print(
                        Panel(
                            f"[bold]{ev.tool_name}[/bold] {ev.tool_input}",
                            title="tool call",
                            border_style="cyan",
                        )
                    )
            elif ev.kind == "tool_result":
                if not print_mode:
                    style = "red" if ev.is_error else "green"
                    console.print(
                        Panel(
                            ev.tool_output[:2000] + ("\n..." if len(ev.tool_output) > 2000 else ""),
                            title=f"{ev.tool_name} result",
                            border_style=style,
                        )
                    )
            elif ev.kind == "compact":
                if not print_mode:
                    console.print(
                        "[yellow]micro-compact: older tool results replaced with placeholders[/yellow]"
                    )
            elif ev.kind == "error":
                err_console.print(f"[bold red]error:[/bold red] {ev.text}")
                return final_text, 1
            elif ev.kind == "turn_end":
                if print_mode:
                    console.print()  # newline
                break
    if not final_text and last_event and last_event.extras.get("final_text"):
        final_text = str(last_event.extras["final_text"])
    if print_mode and final_text:
        # In --print mode, also write a plain copy to stdout for piping.
        # (Already printed live; this is a no-op for normal use.)
        pass
    return final_text, 0


class _NullCtx:
    """A no-op context manager used as a stand-in when --print suppresses spinners."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None


def _confirm_tool(tool_name: str, arguments: dict) -> bool:
    """Prompt the user to confirm a tool call. Returns True to run, False to deny."""
    if not sys.stdin.isatty():
        return False
    console.print(
        Panel(
            f"[bold]{tool_name}[/bold]\n{arguments}",
            title="permission required",
            border_style="yellow",
        )
    )
    try:
        ans = input("Run? [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


async def amain(args: argparse.Namespace) -> int:
    """Async entry point. Returns a process exit code."""
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            max_turns=args.max_turns,
            workspace=args.workspace,
            sandbox=args.sandbox,
            print_mode=args.print_mode,
        )
    except ValueError as e:
        err_console.print(f"[bold red]config error:[/bold red] {e}")
        return 2

    # Detect project context for system-prompt enrichment.
    proj = detect(config.workspace)
    if args.verbose:
        console.print(
            f"[dim]workspace={config.workspace} language={proj.language} "
            f"context_files={[p.name for p in proj.context_files]}[/dim]"
        )
    # Only load project context if --no-context is not set
    if args.no_context:
        system_extra = ""
        if args.verbose:
            console.print("[dim]Skipping project context (--no-context)[/dim]")
    else:
        system_extra = proj.system_prompt_extras()

    try:
        provider = get_provider(
            args.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
    except ValueError as e:
        err_console.print(f"[bold red]provider error:[/bold red] {e}")
        return 2
    try:
        registry = build_default_registry()
        perm = PermissionManager()
        if config.sandbox:
            _apply_sandbox(perm)
        if args.auto_approve:
            # Approve every registered tool. Equivalent to --yes.
            for t in registry.all():
                perm.approve(t.name)
        dispatcher = ToolDispatcher(registry, perm)
        loop = TurnLoop(
            config=config,
            provider=provider,
            registry=registry,
            dispatcher=dispatcher,
            auto_approve_tools=args.auto_approve,
        )

        if args.print_mode:
            if not args.prompt:
                err_console.print(
                    "[bold red]--print requires a prompt argument[/bold red]"
                )
                return 2
            # Patch the dispatcher to interactively confirm when needed.
            original_dispatch = dispatcher.dispatch
            tool_count = 0

            async def confirming_dispatch(name: str, arguments):
                from .tools.dispatcher import ToolNeedsConfirmation as TNC

                try:
                    return await original_dispatch(name, arguments)
                except TNC as e:
                    if _confirm_tool(e.tool_name, arguments):
                        perm.approve(e.tool_name)
                        return await original_dispatch(name, arguments)
                    from .tools.dispatcher import DispatchResult as DR

                    return DR(e.tool_name, "denied by user", is_error=True)

            dispatcher.dispatch = confirming_dispatch  # type: ignore[assignment]
            final_text, code = await run_loop(
                loop, args.prompt, print_mode=True, system_extra=system_extra
            )
            if args.verbose:
                err_console.print(
                    f"[dim]tokens: in={loop.total_input_tokens} "
                    f"out={loop.total_output_tokens} tool_calls={tool_count}[/dim]"
                )
            return code

        # Interactive mode.
        console.print(
            Panel(
                "[bold green]ddw-code[/bold green] — interactive mode\n"
                "Type your request and press Enter. Ctrl-D or `exit` to quit.",
                border_style="green",
            )
        )
        while True:
            try:
                user_input = console.input("[bold blue]>[/bold blue] ")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if user_input.strip().lower() in {"exit", "quit", ":q"}:
                break
            if not user_input.strip():
                continue
            # Same dispatcher behavior in interactive mode.
            original_dispatch = dispatcher.dispatch

            async def confirming_dispatch(name: str, arguments, _orig=original_dispatch):
                from .tools.dispatcher import DispatchResult as DR
                from .tools.dispatcher import ToolNeedsConfirmation as TNC

                try:
                    return await _orig(name, arguments)
                except TNC as e:
                    if _confirm_tool(e.tool_name, arguments):
                        perm.approve(e.tool_name)
                        return await _orig(name, arguments)
                    return DR(e.tool_name, "denied by user", is_error=True)

            dispatcher.dispatch = confirming_dispatch  # type: ignore[assignment]
            final_text, _ = await run_loop(
                loop, user_input, print_mode=False, system_extra=system_extra
            )
            if final_text:
                console.print(Markdown(final_text))
                console.print()
            # Reset prompt-only context extras per turn; keep conversation state.
            system_extra = ""
        return 0
    finally:
        await provider.aclose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        err_console.print("[yellow]interrupted[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
