"""Operator CLI for the SuperSprint core.

    python -m orchestrator.cli run        --repo <path> [--profile minimal]
    python -m orchestrator.cli queue      # show the HITL escalation queue
    python -m orchestrator.cli pause [--lane lane4]
    python -m orchestrator.cli resume
    python -m orchestrator.cli stop
    python -m orchestrator.cli verify <ticket_id>   # check an evidence chain
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .control import Control
from .evidence import EvidenceChain, default_seal_key
from .pipeline import Pipeline
from .policy import load_policy
from .tickets.base import Status
from .tickets.filestore import FileTicketStore


def _paths(args) -> tuple[Path, Path, Path]:
    state = Path(args.state)
    return (state / "tickets.json", state / "evidence", state / "control.json")


def _pipeline(args) -> Pipeline:
    tickets_path, evidence_dir, control_path = _paths(args)
    policy = load_policy(args.policy or f"policy/profiles/{args.profile}.md")
    store = FileTicketStore(tickets_path)
    resolved = [t.title + " " + t.body for t in store.list(Status.DONE)]
    return Pipeline(
        store=store,
        policy=policy,
        repo_path=args.repo,
        evidence_dir=evidence_dir,
        control=Control(control_path),
        base_ref=args.base_ref,
        resolved_corpus=resolved,
    )


def cmd_run(args) -> int:
    pipe = _pipeline(args)
    todo = pipe.store.list(Status.TODO)
    if not todo:
        print("no TODO tickets")
        return 0
    for t in todo:
        res = pipe.process(t.id)
        print(f"{res.ticket_id:10} {res.outcome:10} {res.detail}")
    return 0


def cmd_queue(args) -> int:
    tickets_path, _, _ = _paths(args)
    store = FileTicketStore(tickets_path)
    items = store.list(Status.ESCALATED)
    if not items:
        print("escalation queue empty")
        return 0
    print("HITL escalation queue:")
    for t in items:
        print(f"  {t.id:10} {t.title}")
    return 0


def cmd_pause(args) -> int:
    _, _, control_path = _paths(args)
    Control(control_path).pause(args.lane)
    print(f"paused{' lane ' + args.lane if args.lane else ' (global)'}")
    return 0


def cmd_resume(args) -> int:
    _, _, control_path = _paths(args)
    Control(control_path).resume()
    print("resumed")
    return 0


def cmd_stop(args) -> int:
    _, _, control_path = _paths(args)
    Control(control_path).stop()
    print("stopped (global)")
    return 0


def cmd_verify(args) -> int:
    _, evidence_dir, _ = _paths(args)
    chain = EvidenceChain(Path(evidence_dir) / f"{args.ticket_id}.jsonl")
    ok, reason = chain.verify_chain()
    sealed = chain.verify_seal(default_seal_key())
    print(f"chain integrity: {'OK' if ok else 'BROKEN: ' + str(reason)}")
    print(f"seal valid:      {'yes' if sealed else 'no'}")
    print(f"entries:         {len(chain)}")
    for e in chain:
        print(f"  [{e.seq}] {e.lane}/{e.action}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestrator")
    p.add_argument("--state", default=".supersprint", help="state directory")
    p.add_argument("--repo", default=".", help="target repo to operate on")
    p.add_argument("--policy", default=None, help="explicit policy file path")
    p.add_argument("--profile", default="minimal", help="policy profile name")
    p.add_argument("--base-ref", default="HEAD")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(func=cmd_run)
    sub.add_parser("queue").set_defaults(func=cmd_queue)
    pp = sub.add_parser("pause")
    pp.add_argument("--lane", default=None)
    pp.set_defaults(func=cmd_pause)
    sub.add_parser("resume").set_defaults(func=cmd_resume)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    vp = sub.add_parser("verify")
    vp.add_argument("ticket_id")
    vp.set_defaults(func=cmd_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
