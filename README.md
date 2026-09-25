# Suprm Sounds

An artist-first music distribution platform. Artists upload releases, split royalties with
collaborators, and track every cent. Suprm Sounds delivers releases to stores as
DDEX ERN packages, imports store royalty reports, and pays artists through Stripe Connect.

**Start with [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md).** It explains how to get connected to
stores (a white-label backend first, then direct feeds), what paperwork you need, and what's
left to build.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then edit it

suprm init-db
suprm create-admin you@suprmsounds.com
suprm add-target "Local test" local --party-id PADPIDA0000000000T --party-name "Test Store" \
    --config '{"path": "./outbox/_delivered"}'

uvicorn suprm.main:app --reload     # http://localhost:8000
python -m pytest                    # run the tests
```

## How a release flows

1. **Artist** signs up, creates a release, uploads WAV/FLAC and 3000×3000 cover art, adds
   credits and splits (any email; collaborators without an account get paid once they sign up),
   fixes anything the pre-flight check flags, and submits.
2. **Admin** (`/admin`) listens and reviews, then approves. UPC and ISRCs are assigned
   automatically. The admin then delivers to one or more targets. Each delivery builds a DDEX batch in
   `outbox/<target>/<batch_id>/` and uploads it (SFTP, S3, HTTP or a local folder).
3. **Each month**, admin imports store or backend reports (`/admin/royalties`) and clicks
   **Allocate**. Money is split by each track's percentages, minus the platform commission, into
   each artist's ledger.
4. **Payouts** (`/admin/payouts`, or `suprm run-payouts` from cron): every artist with a
   verified Stripe account and a balance over `MIN_PAYOUT_USD` gets a Stripe transfer.

## Layout

```
suprm/
  models.py            database schema (money stored exactly, as 1e-8 USD integers)
  qc.py, media.py      store-rule checks, audio/artwork inspection
  identifiers.py       UPC / ISRC generation + validation
  ddex/                ERN 4.3 builder + batch packager
  delivery/            transports (local/sftp/s3/http) + delivery service
  royalties/           report importer + split ledger
  payouts/             Stripe Connect
  web/                 FastAPI app, templates, styles
  cli.py               admin commands
tests/                 unit tests + a full artist→store→royalty→payout run
docs/BLUEPRINT.md      business + technical launch plan
```

## Stripe webhook

Point a Stripe webhook at `https://<your-domain>/webhooks/stripe` for the `account.updated` event
and put its signing secret in `STRIPE_WEBHOOK_SECRET`. This keeps each artist's payout status in sync.
