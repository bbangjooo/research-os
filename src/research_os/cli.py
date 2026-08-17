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
from .discovery import NOTE_KINDS
from .discovery_service import DiscoveryService
from .errors import ResearchOSError
from .frame_transition_service import FrameTransitionService
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
    agent_context.add_argument(
        "--schema-version",
        type=int,
        choices=(2, 3),
        default=3,
        help="agent context packet schema (default: 3; use 2 for compatibility)",
    )

    baseline = subparsers.add_parser(
        "baseline", help="measure and seal a reproducible baseline"
    )
    baseline.add_argument(
        "--repeats",
        type=int,
        help="must equal the immutable constitution repetition count",
    )
    baseline.add_argument(
        "--evaluation-scope-id",
        dest="evaluation_scope_id",
        action=_SingleValue,
        help="preregistered StudyContract v2 evaluation scope",
    )

    run_once = subparsers.add_parser(
        "run-once", help="evaluate one candidate JSON object"
    )
    run_once.add_argument("candidate", type=Path)
    run_once.add_argument(
        "--proposal",
        type=Path,
        action=_SingleValue,
        help="strict StudyContract v2 Proposal JSON",
    )
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

    diagnose = subparsers.add_parser(
        "diagnose",
        help="record one evidence-bound Diagnosis for a terminal experiment",
    )
    diagnose.add_argument(
        "diagnosis",
        type=Path,
        help="strict Diagnosis JSON",
    )

    diagnosis_template = subparsers.add_parser(
        "diagnosis-template",
        help="emit a no-write Diagnosis body with exact kernel evidence",
    )
    diagnosis_template.add_argument(
        "--experiment",
        dest="experiment_id",
        help="pending terminal experiment (optional when exactly one is pending)",
    )

    open_generation = subparsers.add_parser(
        "open-generation",
        help="open an evaluation-sealed study generation from a strict contract",
    )
    open_generation.add_argument(
        "contract",
        type=Path,
        help="strict StudyContract JSON",
    )
    open_generation.add_argument(
        "--predecessor-generation-id",
        "--predecessor",
        dest="predecessor_generation_id",
        action=_SingleValue,
        help="active generation being explicitly superseded",
    )
    open_generation.add_argument(
        "--change-reason",
        "--reason",
        dest="change_reason",
        action=_SingleValue,
        help="non-empty reason required for a successor generation",
    )

    frame_gate_a = subparsers.add_parser(
        "frame-transition-gate-a",
        help="record a deterministic controlled frame-transition Gate A receipt",
    )
    frame_gate_a.add_argument("gate", type=Path, help="strict Gate A JSON")

    frame_open = subparsers.add_parser(
        "frame-transition-open",
        help="open a material outer frame-transition inquiry",
    )
    frame_open.add_argument("inquiry", type=Path, help="strict inquiry JSON")

    frame_decide = subparsers.add_parser(
        "frame-transition-decide",
        help="record a comparative frame-transition decision",
    )
    frame_decide.add_argument("decision", type=Path, help="strict decision JSON")

    frame_authorize_pilot = subparsers.add_parser(
        "frame-transition-authorize-pilot",
        help="record distinct PILOT_ONLY authority",
    )
    frame_authorize_pilot.add_argument(
        "authorization",
        type=Path,
        help="strict pilot authorization JSON",
    )

    frame_record_pilot = subparsers.add_parser(
        "frame-transition-record-pilot",
        help="record a controlled three-arm pilot result",
    )
    frame_record_pilot.add_argument(
        "pilot_result",
        type=Path,
        help="strict pilot result JSON",
    )

    frame_review = subparsers.add_parser(
        "frame-transition-review",
        help="record a fresh independent adoption review",
    )
    frame_review.add_argument("review", type=Path, help="strict adoption review JSON")

    frame_adopt_policy = subparsers.add_parser(
        "frame-transition-adopt-policy",
        help="record deterministic built-in POLICY_ADOPTION for an approved inquiry",
    )
    frame_adopt_policy.add_argument(
        "inquiry_id",
        help="approved inquiry identifier",
    )

    frame_revoke = subparsers.add_parser(
        "frame-transition-revoke",
        help="revoke an exact frame-transition authority receipt",
    )
    frame_revoke.add_argument("revocation", type=Path, help="strict revocation JSON")

    frame_activate = subparsers.add_parser(
        "frame-transition-activate",
        help="separately write the current policy-adopted successor state",
    )
    frame_activate.add_argument("inquiry_id", help="policy-adopted inquiry identifier")
    frame_activate.add_argument(
        "contract",
        type=Path,
        help="strict successor StudyContract JSON",
    )

    frame_status = subparsers.add_parser(
        "frame-transition-status",
        help="show replay-derived controlled frame-transition state",
    )
    frame_status.add_argument(
        "--inquiry",
        dest="inquiry_id",
        help="limit status to one inquiry identifier",
    )

    discovery_note = subparsers.add_parser(
        "discovery-note",
        help="append one screened advisory discovery note",
    )
    discovery_note.add_argument("note", type=Path, help="strict discovery note JSON")

    discovery_status = subparsers.add_parser(
        "discovery-status",
        help="show the replay-derived advisory discovery journal",
    )
    discovery_status.add_argument(
        "--kind",
        dest="kind",
        choices=sorted(NOTE_KINDS),
        help="limit the journal to one note kind",
    )
    discovery_status.add_argument(
        "--limit",
        dest="limit",
        type=int,
        help="return only the most recent N notes",
    )
    discovery_view = discovery_status.add_mutually_exclusive_group()
    discovery_view.add_argument(
        "--exhaustion",
        dest="exhaustion",
        action="store_true",
        help="show which exhaustion signal kinds currently have material",
    )
    discovery_view.add_argument(
        "--residual",
        dest="residual",
        action="store_true",
        help="show the residual generation task for each closed hypothesis class",
    )
    discovery_view.add_argument(
        "--yield",
        dest="yield_curve",
        action="store_true",
        help="show the admissible-distinct draft yield curve",
    )

    discovery_analogies = subparsers.add_parser(
        "discovery-analogies",
        help="read cross-frame claims as advisory material",
    )
    discovery_analogies.add_argument("query", type=Path, help="strict analogy query JSON")
    discovery_analogies.add_argument(
        "--program-root",
        dest="program_root",
        required=True,
        type=Path,
        help="ProgramStore root directory",
    )
    discovery_analogies.add_argument(
        "--program-id",
        dest="program_id",
        required=True,
        help="ProgramStore program identifier",
    )

    subparsers.add_parser(
        "study-status",
        help="show the replay-derived active study generation and reserved budget",
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
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    )
    stream.write(rendered + "\n")


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "run-once" and args.proposal is not None:
        conflicts = [
            option
            for option, value in (
                ("--parent", args.parent_id),
                ("--graph-action", args.graph_action),
                ("--scientific-change", args.scientific_change),
            )
            if value is not None
        ]
        if conflicts:
            raise CLIUsageError(
                "--proposal cannot be combined with " + ", ".join(conflicts)
            )
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

    if args.command.startswith("frame-transition-"):
        frame_service = FrameTransitionService(args.project)
        if args.command == "frame-transition-gate-a":
            return frame_service.gate_a(args.gate)
        if args.command == "frame-transition-open":
            return frame_service.open_inquiry(args.inquiry)
        if args.command == "frame-transition-decide":
            return frame_service.decide_inquiry(args.decision)
        if args.command == "frame-transition-authorize-pilot":
            return frame_service.authorize_pilot(args.authorization)
        if args.command == "frame-transition-record-pilot":
            return frame_service.record_pilot(args.pilot_result)
        if args.command == "frame-transition-review":
            return frame_service.review_adoption(args.review)
        if args.command == "frame-transition-adopt-policy":
            return frame_service.adopt_policy(args.inquiry_id)
        if args.command == "frame-transition-revoke":
            return frame_service.revoke_authority(args.revocation)
        if args.command == "frame-transition-activate":
            return frame_service.activate(args.inquiry_id, args.contract)
        if args.command == "frame-transition-status":
            return frame_service.status(args.inquiry_id)
        raise AssertionError(f"unhandled frame-transition command: {args.command}")

    if args.command.startswith("discovery-"):
        discovery_service = DiscoveryService(args.project)
        if args.command == "discovery-note":
            return discovery_service.note(args.note)
        if args.command == "discovery-status":
            if args.exhaustion:
                return discovery_service.exhaustion()
            if args.residual:
                return discovery_service.residual()
            if args.yield_curve:
                return discovery_service.yield_curve()
            return discovery_service.status(kind=args.kind, limit=args.limit)
        if args.command == "discovery-analogies":
            return discovery_service.analogies(
                args.query,
                program_root=args.program_root,
                program_id=args.program_id,
            )
        raise AssertionError(f"unhandled discovery command: {args.command}")

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
        return service.agent_context(
            limit=args.limit,
            schema_version=args.schema_version,
        )
    if args.command == "baseline":
        if (
            args.repeats is not None
            and args.repeats != service.config.baseline_repeats
        ):
            raise ValueError(
                "--repeats must equal the immutable constitution repetition count "
                f"({service.config.baseline_repeats})"
            )
        if args.evaluation_scope_id is None:
            return service.baseline()
        return service.baseline(evaluation_scope_id=args.evaluation_scope_id)
    if args.command == "run-once":
        run_arguments: dict[str, Any] = {
            "parent_id": args.parent_id,
            "retry_of": args.retry_of,
            "context_token": args.context_token,
            "graph_action": args.graph_action,
            "scientific_change": args.scientific_change,
        }
        if args.proposal is not None:
            run_arguments["proposal"] = args.proposal
        return service.run_once(args.candidate, **run_arguments)
    if args.command == "conclude-branch":
        return service.conclude_branch(
            args.conclusion,
            context_token=args.context_token,
        )
    if args.command == "diagnose":
        return service.record_diagnosis(args.diagnosis)
    if args.command == "diagnosis-template":
        return service.diagnosis_template(args.experiment_id)
    if args.command == "open-generation":
        return service.open_generation(
            args.contract,
            predecessor_generation_id=args.predecessor_generation_id,
            change_reason=args.change_reason,
        )
    if args.command == "study-status":
        return service.study_status()
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
