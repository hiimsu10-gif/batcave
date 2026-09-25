"""Admin command line.

    suprm init-db
    suprm create-admin you@suprmsounds.com
    suprm add-target "Local test" local --party-id PADPIDA0000000000T --party-name "Test Store" \
        --config '{"path": "./outbox/_delivered"}'
    suprm deliver <release_id> <target_name> [--takedown]
    suprm import-royalties report.csv --source FUGA --period 2026-08 [--allocate]
    suprm run-payouts            # run from cron, e.g. monthly
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal, init_db
from .models import DeliveryKind, DeliveryTarget, Release, Role, User


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="suprm")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    a = sub.add_parser("create-admin")
    a.add_argument("email")
    a.add_argument("--name", default="Suprm Admin")
    t = sub.add_parser("add-target")
    t.add_argument("name")
    t.add_argument("transport", choices=["local", "sftp", "s3", "http"])
    t.add_argument("--party-id", required=True)
    t.add_argument("--party-name", required=True)
    t.add_argument("--config", default="{}")
    t.add_argument("--live", action="store_true", help="send LiveMessage instead of TestMessage")
    d = sub.add_parser("deliver")
    d.add_argument("release_id", type=int)
    d.add_argument("target")
    d.add_argument("--takedown", action="store_true")
    d.add_argument("--update", action="store_true")
    r = sub.add_parser("import-royalties")
    r.add_argument("file", type=Path)
    r.add_argument("--source", required=True)
    r.add_argument("--period", required=True)
    r.add_argument("--currency", default="USD")
    r.add_argument("--allocate", action="store_true")
    sub.add_parser("run-payouts")
    args = p.parse_args(argv)

    init_db()
    session = SessionLocal()
    try:
        if args.cmd == "init-db":
            print("Database ready")
        elif args.cmd == "create-admin":
            from .security import hash_password

            pw = getpass.getpass("Password (10+ chars): ")
            if len(pw) < 10:
                print("Password too short", file=sys.stderr)
                return 1
            user = session.scalar(select(User).where(User.email == args.email.lower()))
            if user:
                user.role, user.password_hash = Role.admin, hash_password(pw)
            else:
                session.add(User(email=args.email.lower(), password_hash=hash_password(pw),
                                 display_name=args.name, role=Role.admin))
            session.commit()
            print(f"Admin {args.email} ready")
        elif args.cmd == "add-target":
            session.add(DeliveryTarget(name=args.name, transport=args.transport, config=json.loads(args.config),
                                       recipient_party_id=args.party_id, recipient_party_name=args.party_name,
                                       test_mode=not args.live))
            session.commit()
            print(f"Target {args.name} added ({'LIVE' if args.live else 'TEST'} mode)")
        elif args.cmd == "deliver":
            from .delivery.service import deliver

            release = session.get(Release, args.release_id)
            target = session.scalar(select(DeliveryTarget).where(DeliveryTarget.name == args.target))
            if not release or not target:
                print("Release or target not found", file=sys.stderr)
                return 1
            kind = DeliveryKind.takedown if args.takedown else DeliveryKind.update if args.update else DeliveryKind.insert
            result = deliver(session, release, target, kind)
            print(f"{result.status.value}: {result.error or result.remote_ref}")
            return 0 if result.status.value != "failed" else 1
        elif args.cmd == "import-royalties":
            from .royalties.importer import import_report
            from .royalties.ledger import allocate_statement

            res = import_report(session, args.file.read_bytes(), source=args.source, period=args.period,
                                filename=args.file.name, currency=args.currency)
            st = res.statement
            print(f"{'Already imported' if res.duplicate else 'Imported'} statement #{st.id}: "
                  f"{st.line_count} lines, gross {st.gross_amount}, {st.unmatched_count} unmatched")
            if args.allocate:
                print(f"Allocated {allocate_statement(session, st)} lines")
        elif args.cmd == "run-payouts":
            from .payouts.stripe_connect import get_gateway, run_payouts

            for payout in run_payouts(session, get_gateway()):
                print(f"#{payout.id} {payout.user.email} {payout.amount} {payout.status.value} {payout.error or ''}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
