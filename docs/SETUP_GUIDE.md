# Suprm Sounds: Setup Guide

Your LLC and EIN are done. This guide covers everything else, in the order to do it.
Each step says what it's for, where to go, and what to put in your `.env` file.

Prices and requirements change, so confirm them on each official site before paying.

---

## Week 1: identity and money

### 1. Business bank accounts
- [ ] **Operating account** for your own revenue and expenses (e.g. Mercury, Relay, your local bank).
- [ ] **Artist funds account**: a *second* account that only holds royalties owed to artists. Stores and your backend pay into it, and you fund Stripe payouts from it. Keeping artists' money separate from yours protects you in an audit or dispute, and makes month-end reconciliation easy.

### 2. Stripe Connect (artist payouts)
1. Create a Stripe account for the LLC at stripe.com, using your EIN and the operating bank account.
2. Dashboard → **Connect** → Get started → choose **Platform or marketplace**.
3. Account type: **Express**. Stripe collects artist identity checks, bank details and W-9/W-8 forms.
4. Connect → Settings → **Tax reporting**: turn on 1099 delivery for US artists.
5. Connect → Settings → **Branding**: add the Suprm Sounds logo and colors so artist onboarding looks like you.
6. Developers → API keys: copy the **test** secret key into `.env` as `STRIPE_SECRET_KEY` (it starts with `sk_test_`).
7. Developers → Webhooks → add endpoint `https://<your-domain>/webhooks/stripe`, event `account.updated`. Copy the signing secret into `STRIPE_WEBHOOK_SECRET`.
8. Run one full test payout end to end, then swap in the **live** keys.

Payouts only draw on your *Stripe balance*. Each month, top it up from the artist funds account before clicking **Run payouts**.

### 3. DDEX Party ID (DPID): free
Every DDEX message you send is signed with this ID.
- [ ] Request it at **dpid.ddex.net** using the legal entity name exactly as registered.
- [ ] `.env`: `DDEX_PARTY_ID=PADPIDA...` and `DDEX_PARTY_NAME=Suprm Sounds`

### 4. Barcodes: UPC for releases
- [ ] Buy a **GS1 US Company Prefix** at gs1us.org (annual fee, priced by how many barcodes you need; start with the smallest tier that covers at least 100). Don't buy single barcodes one at a time: those don't include a company prefix, and the platform needs one to number UPCs automatically.
- [ ] `.env`: `UPC_COMPANY_PREFIX=` (the digits GS1 gives you)
- If your backend includes free UPCs, you can skip this at first. Leave the prefix empty and enter the UPCs they give you on each release.

### 5. ISRC registrant code: tracks
- [ ] Apply at **usisrc.org** as a US registrant (small one-time fee). You'll get a 3-character registrant code.
- [ ] `.env`: `ISRC_COUNTRY=US`, `ISRC_REGISTRANT=` (your 3 characters)
- The platform numbers ISRCs automatically: `US` + your code + year + a 5-digit sequence.

### 6. DMCA agent
- [ ] Register a designated agent with the US Copyright Office at **dmca.copyright.gov** (small fee; renew every 3 years).
- [ ] Use the same email you set as `SUPPORT_EMAIL`.

### 7. Legal documents
The drafts are in `suprm/legal/` and show on the site at `/legal/...`:
- `terms.md`: Terms of Service
- `artist-agreement.md`: Artist Distribution Agreement
- `privacy.md`: Privacy Policy
- `content-policy.md`: Content & Fraud Policy

- [ ] Fill in `LEGAL_ENTITY_NAME`, `LEGAL_STATE`, `LEGAL_ADDRESS`, `SUPPORT_EMAIL` in `.env`. The pages update automatically.
- [ ] **Have a music or entertainment attorney review all four before launch.** Section 9 of the Terms leaves the court-or-arbitration choice open for them.
- [ ] Each time a document changes, bump `LEGAL_VERSION`. The site records which version each artist accepted.

---

## Week 2: choose your delivery backend

### 8. Get quotes
Send the email below to 3+ vendors (Revelator, SonoSuite, FUGA, Label Engine, and label-services teams at established distributors). Compare the replies in a table: monthly minimum, fee per release, revenue share, stores covered, delivery method, report format, payment timing.

> **Subject:** White-label distribution backend for Suprm Sounds
>
> Hi [Name],
>
> I run Suprm Sounds, an artist-first distribution platform (Suprm Sounds LLC). We've built our own artist
> platform: uploads, QC, metadata, royalty splits and payouts. We're looking for a backend partner to
> deliver our catalog to stores under our own brand.
>
> Could you share:
> 1. Pricing: monthly minimums, per-release fees, and your revenue share
> 2. Store coverage, including YouTube Content ID, TikTok/SoundOn, Meta, and emerging markets
> 3. How you accept deliveries: DDEX ERN 4.3 over SFTP/S3, or an API (docs link?)
> 4. Sales report format and schedule, and when payments are made after month-end
> 5. White-label terms: will our artists ever see your brand?
> 6. Fraud monitoring, and how store penalties for artificial streaming are passed on
> 7. Minimum catalog size or volume requirements
>
> We're launching with [N] artists and about [N] releases in the first 6 months.
>
> Thanks,
> [Your name]
> Suprm Sounds · [phone] · [website]

### 9. Connect the backend you pick
- **They accept DDEX over SFTP:** Admin → Delivery targets → add an `sftp` target with their host, username, key path, remote folder, host key and their DPID.
- **They have an API:** send me their API docs and I'll write the adapter (it goes in `suprm/delivery/transports.py`).
- Send 2–3 test releases in **TEST** mode, fix anything their QC flags, then switch the target to **LIVE**.

---

## Week 3: go online

### 10. Hosting
Any host that runs Python works (Render, Railway, Fly.io, a VPS). You need:

| Piece | What to use | `.env` |
|---|---|---|
| Web app | `uvicorn suprm.main:app` (see `Procfile`) | `BASE_URL=https://suprmsounds.com` |
| Worker | `suprm worker` running all the time (sends deliveries) | `JOBS_INLINE=false` |
| Database | Managed Postgres (the host's add-on, Neon or Supabase) | `DATABASE_URL=postgresql+psycopg://...` |
| Migrations | `suprm migrate` on every deploy (the `release:` line in `Procfile`) | |
| File storage | **Cloudflare R2** (no fees for downloading, which matters for big WAVs), or AWS S3 | `STORAGE_BACKEND=s3`, `S3_*` |
| Email | Resend or Postmark (verify your domain's SPF and DKIM records) | `EMAIL_BACKEND=resend`, `RESEND_API_KEY` |
| Secrets | A long random `SECRET_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) | `SECRET_KEY` |

Install with `pip install -e ".[postgres]"` in production.

### 11. First admin
```bash
suprm migrate
suprm create-admin you@suprmsounds.com
```
Log in, and the site will ask you to set up two-factor login before the admin console opens.

---

## Every month

1. Download the backend's royalty report once it arrives (often 30–60 days after month-end).
2. Admin → Royalty imports → upload it → check unmatched lines → **Allocate**.
3. Move the total owed from the artist funds account into Stripe.
4. Admin → Payouts → **Run payouts**.
5. Save the report and the payout history for your bookkeeper.
