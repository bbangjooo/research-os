"""Command-line entry point for Research OS."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Never, Sequence

from . import __version__
from .agent_install import install_agent_skill
from .errors import ResearchOSError
from .scaffold import initialize_project
from .service import ResearchService


class CLIUsageError(ValueError):
    """A command-line syntax failure rendered through the JSON error contract."""

    code = "CLI_USAGE"


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CLIUsageError(message)


class _SingleValue(argparse.Action):
    """Reject repeated scientific metadata instead of silently taking the last."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            raise CLIUsageError(f"{option_string or self.dest} may be supplied once")
        setattr(namespace, self.dest, values)


def _parser() -> argparse.ArgumentParser:
    parser = _JSONArgumentParser(
        prog="research-os",
        description="Local-first control plane for bounded, auditable experiments.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="project root (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init", help="add a non-overwriting scaffold to an existing project directory"
    )
    init.add_argument("path", type=Path, help="existing project root")
    init.add_argument("--id", required=True, dest="project_id")
    init.add_argument("--name", required=True)

    install_skill = subparsers.add_parser(
        "install-agent-skill",
        help="install the Research OS skill for Codex and/or Claude Code",
    )
    install_skill.add_argument(
        "--target",
        choices=("all", "codex", "claude"),
        default="all",
        help="agent skill host (default: all)",
    )
    install_skill.add_argument(
        "--upgrade",
        action="store_true",
        help="replace only an exact, recognized prior Research OS skill release",
    )

    subparsers.add_parser("inspect", help="show the resolved project contract")
    subparsers.add_parser("doctor", help="validate adapter and immutable inputs")
    subparsers.add_parser(
        "evaluator-review-subject",
        help="emit the exact current evaluator subject for independent review",
    )

    certify = subparsers.add_parser(
        "certify-evaluator",
        help="bind an independent evaluator review to current scientific inputs",
    )
    certify.add_argument("review", type=Path, help="strict evaluator review JSON")
    certify.add_argument(
        "--replace",
        action="store_true",
        help="explicitly replace the existing managed certification",
    )

    agent_context = subparsers.add_parser(
        "agent-context",
        help="emit one bounded context packet for Codex or Claude Code",
    )
    agent_context.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum recent records per context section (1-100)",
    )

    baseline = subparsers.add_parser(
        "baseline", help="measure and seal a reproducible baseline"
    )
    baseline.add_argument(
        "--repeats",
        type=int,
        help="must equal the immutable constitution repetition count",
    )

    run_once = subparsers.add_parser(
        "run-once", help="evaluate one candidate JSON object"
    )
    run_once.add_argument("candidate", type=Path)
    run_once.add_argument("--parent", dest="parent_id")
    run_once.add_argument(
        "--retry-of",
        dest="retry_of",
        help="explicitly retry the most recent retryable attempt",
    )
    run_once.add_argument(
        "--context-token",
        dest="context_token",
        help="require the canonical agent-context snapshot to still be current",
    )
    run_once.add_argument(
        "--graph-action",
        choices=("explore", "exploit", "ablate", "replicate"),
        action=_SingleValue,
        help="scientific graph operation for a new agent-proposed node",
    )
    run_once.add_argument(
        "--scientific-change",
        action=_SingleValue,
        help="the one conceptual intervention made by this candidate",
    )

    conclude = subparsers.add_parser(
        "conclude-branch",
        help="record an evidence-bound interpretation that closes or redirects a branch",
    )
    conclude.add_argument("conclusion", type=Path, help="strict conclusion JSON")
    conclude.add_argument(
        "--context-token",
        required=True,
        dest="context_token",
        help="require the canonical agent-context snapshot to still be current",
    )

    subparsers.add_parser("status", help="show projected project status")

    lineage = subparsers.add_parser(
        "lineage", help="show the experiment DAG or one ancestry chain"
    )
    lineage.add_argument("--experiment", dest="experiment_id")

    artifacts = subparsers.add_parser(
        "artifacts", help="list experiment artifact records"
    )
    artifacts.add_argument("--experiment", dest="experiment_id")

    findings = subparsers.add_parser("findings", help="list durable research findings")
    findings.add_argument("--experiment", dest="experiment_id")

    subparsers.add_parser(
        "replay", help="verify events and rebuild the SQLite projection"
    )
    return parser


def _print(value: Any, *, stream: Any | None = None) -> None:
    stream = sys.stdout if stream is None else stream
    json.dump(
        value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    )
    stream.write("\n")


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "init":
        created = initialize_project(args.path, args.project_id, args.name)
        return {
            "project_id": args.project_id,
            "root": str(args.path.expanduser().resolve()),
            "created": [str(path) for path in created],
            "next": (
                "open the project in Codex or Claude Code, configure the research "
                "brief/schema and adapter/evaluator, then let the agent run doctor"
            ),
        }
    if args.command == "install-agent-skill":
        return {
            "skill": "research-os",
            "installations": install_agent_skill(
                args.target,
                upgrade=args.upgrade,
            ),
            "next": "start Codex or Claude Code in a Research OS project and ask it to conduct research",
        }

    service = ResearchService(args.project)
    if args.command == "inspect":
        return service.inspect()
    if args.command == "doctor":
        return service.doctor().to_dict()
    if args.command == "evaluator-review-subject":
        return service.evaluator_review_subject()
    if args.command == "certify-evaluator":
        return service.certify_evaluator(args.review, replace=args.replace)
    if args.command == "agent-context":
        return service.agent_context(limit=args.limit)
    if args.command == "baseline":
        if (
            args.repeats is not None
            and args.repeats != service.config.baseline_repeats
        ):
            raise ValueError(
                "--repeats must equal the immutable constitution repetition count "
                f"({service.config.baseline_repeats})"
            )
        return service.baseline()
    if args.command == "run-once":
        return service.run_once(
            args.candidate,
            parent_id=args.parent_id,
            retry_of=args.retry_of,
            context_token=args.context_token,
            graph_action=args.graph_action,
            scientific_change=args.scientific_change,
        )
    if args.command == "conclude-branch":
        return service.conclude_branch(
            args.conclusion,
            context_token=args.context_token,
        )
    if args.command == "status":
        return service.status()
    if args.command == "lineage":
        return service.lineage(args.experiment_id)
    if args.command == "artifacts":
        return service.artifacts(args.experiment_id)
    if args.command == "findings":
        return service.findings(args.experiment_id)
    if args.command == "replay":
        return service.replay()
    raise AssertionError(f"unhandled command: {args.command}")


def _validated_recovery_paths(exc: BaseException) -> list[str]:
    value = getattr(exc, "recovery_paths", ())
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return []
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or "\x00" in item:
            return []
        path = Path(item)
        if not path.is_absolute():
            return []
        paths.append(str(path))
    return list(dict.fromkeys(paths))


def _validated_rollback_errors(exc: BaseException) -> list[str]:
    value = getattr(exc, "rollback_errors", ())
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return []
    errors: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or "\x00" in item:
            return []
        errors.append(item)
    return list(dict.fromkeys(errors))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        _print(_dispatch(args))
        return 0
    except KeyboardInterrupt as exc:
        error: dict[str, Any] = {
            "type": "KeyboardInterrupt",
            "message": "cancelled",
        }
        recovery_paths = _validated_recovery_paths(exc)
        if recovery_paths:
            error["recovery_paths"] = recovery_paths
        rollback_errors = _validated_rollback_errors(exc)
        if rollback_errors:
            error["rollback_errors"] = rollback_errors
        _print(
            {
                "ok": False,
                "error": error,
            },
            stream=sys.stderr,
        )
        return 130
    except (ResearchOSError, OSError, TypeError, ValueError) as exc:
        error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            error["code"] = code
        details = getattr(exc, "details", None)
        if isinstance(details, Mapping):
            error["details"] = dict(details)
        recovery_paths = _validated_recovery_paths(exc)
        if recovery_paths:
            error["recovery_paths"] = recovery_paths
        rollback_errors = _validated_rollback_errors(exc)
        if rollback_errors:
            error["rollback_errors"] = rollback_errors
        _print({"ok": False, "error": error}, stream=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
