# Suprm Sounds: Distribution Business Blueprint

> Suprm Sounds is an artist-first distributor. We get music onto every major
> store, show artists every cent they earn, split royalties automatically, and pay
> everyone through Stripe.

Status as of September 2026. The costs and store policies below change often, so
confirm them with each vendor before you sign anything.

---

## 1. What stops a new distributor from connecting to the stores

The delivery technology is standardized and is now built in this repo. What
actually limits a new distributor is **permission**:

| Needed to deliver direct to a store | Why it's hard on day 1 |
|---|---|
| A signed content-provider / licensor agreement with each store | Spotify, Apple, Amazon, YouTube, TikTok and Meta each review applicants. They expect a company that exists, a meaningful catalog and a clean record on rights and fraud. Tiny brand-new catalogs are usually turned down. |
| Store-specific onboarding (SFTP credentials, test deliveries, style-guide QC) | Every store has its own spec and QC team. Expect weeks per store. |
| Anti-fraud obligations | Stores penalize distributors for artificial streams on their catalog, and some charge per-track fees. You need your own screening. |

**So the plan is hybrid.** You own the artist relationship and the platform
(this repo). Store delivery goes through a white-label backend that already has
every store contract. As your catalog grows, you move stores to direct feeds
one at a time. The code is built for this: a backend and a direct store feed are
both just a **delivery target**.

```
          Artists
            │  upload, splits, earnings, payouts
            ▼
 ┌────────────────────────────┐
 │  Suprm Sounds platform     │  ← this repo
 │  QC · DDEX · ledger · pay  │
 └─────┬───────────────┬──────┘
       │ Phase 1       │ Phase 2+
       ▼               ▼
 White-label backend   Direct DSP feeds (SFTP/S3, DDEX ERN)
 (FUGA / Revelator /   Spotify, Apple, Amazon, Deezer, TIDAL...
  SonoSuite ...)
       │               │
       └──► 150+ stores ◄──┘
                │ monthly sales reports + money
                ▼
   Royalty import → splits → artist balances → Stripe Connect payouts
```

---

## 2. What's built (this repo)

| Area | What it does | Where |
|---|---|---|
| Artist web app | Sign-up, multiple artist names, releases, track upload, credits, royalty splits by email, pre-flight QC, earnings by store/country/month/track, Stripe payout onboarding | `suprm/web/` |
| QC engine | Checks audio (WAV/FLAC, 44.1 kHz+, stereo), 3000×3000 square artwork, splits totalling 100%, songwriter credits, and store style-guide rules (no "feat." in titles, no emoji, no ALL CAPS, release-type track counts) | `suprm/qc.py`, `suprm/media.py` |
| Codes | UPC (GS1) and ISRC generation with check digits, assigned automatically on approval | `suprm/identifiers.py` |
| DDEX engine | Builds ERN 4.3 NewReleaseMessage XML with MD5-hashed resources, in the batch folder layout stores expect, including `BatchComplete_*.xml`. Handles inserts, updates and takedowns. | `suprm/ddex/` |
| Delivery transports | `local`, `sftp` (with host-key pinning), `s3`, `http` (white-label backend APIs). Each target has a TEST/LIVE switch. | `suprm/delivery/` |
| Royalty import | Reads any CSV/TSV store or backend report by recognizing its column names. Handles European decimal commas, skips files it has already imported, and flags ISRCs it can't match. | `suprm/royalties/importer.py` |
| Ledger | Append-only and precise to $0.00000001. Applies the platform commission and splits, pays out every cent including rounding remainders, and holds money for invited collaborators until they sign up. | `suprm/royalties/ledger.py` |
| Payouts | Stripe Connect Express accounts and transfers with duplicate-payment protection. Failed transfers go back to the artist's balance. Pays whole cents only; fractions carry over. | `suprm/payouts/` |
| Admin console | Review queue, approve/reject with notes, deliver to targets, target management, report import and allocation, payout runs | `suprm/web/routes_admin.py` |
| CLI | Setup, delivery, imports and payouts, all scriptable for cron | `suprm/cli.py` |

---

## 3. Launch checklist (Phase 0: before the first artist)

Business and identity:
- [x] **Entity.** Suprm Sounds is registered, with an EIN.
- [ ] **Business bank account** (e.g. Mercury), where store and backend royalties land.
- [ ] **Stripe account** with Connect enabled, using the Express account type. In test mode, run the full flow first.
- [ ] **DDEX Party ID (DPID).** Free; request it at dpid.ddex.net. Put it in `DDEX_PARTY_ID`.
- [ ] **GS1 US company prefix** for UPCs (annual fee, priced by how many barcodes you need). Put it in `UPC_COMPANY_PREFIX`.
      *Or* let your backend assign UPCs until you have volume.
- [ ] **ISRC registrant code** from usisrc.org (small one-time fee). Put it in `ISRC_REGISTRANT`.

Legal documents (have a music attorney draft or review these):
- [ ] **Artist Distribution Agreement / Terms.** Non-exclusive grant of distribution rights; the artist warrants they own or cleared everything (samples, covers, beats); your commission or fees; payment timing; takedown on request; your right to withhold and claw back money for fraud or chargebacks.
- [ ] **Artificial streaming and AI content policy.** Stores penalize distributors for fraud. Reserve the right to reject releases, hold payments and ban accounts.
- [ ] **Split terms.** The payee who accepts a split agrees to the terms. The uploader warrants that the split percentages are right.
- [ ] **Privacy policy and DMCA agent registration** (US Copyright Office).
- [ ] **Covers and publishing.** This platform pays *master* (sound recording) royalties. Songwriter and publishing royalties flow through PROs (BMI/ASCAP) and The MLC. Cover songs need mechanical licenses for downloads. Say this clearly in the terms.

Money and tax:
- [ ] Stripe Connect collects W-9/W-8 details and files the 1099s for Express accounts. Confirm the setup in your Stripe dashboard.
- [ ] Decide whether you're **holding artist money in trust**. Keep artist balances in a separate bank account from operating cash. Ask your CPA and attorney whether any money-transmission rules apply in your state. Using Stripe Connect as the payment processor is the standard way to avoid becoming a money transmitter yourself.
- [ ] Pick a **payout cadence**, such as monthly, after the backend pays you. Never pay artists money you haven't received yet.

---

## 4. Phase 1: launch through a white-label backend

1. **Get quotes from 3+ white-label or B2B distribution backends.** Names to look at:
   Revelator, SonoSuite, FUGA, Label Engine/Labelcamp, and B2B programs from
   established distributors (e.g. Symphonic, Believe/TuneCore for labels). Ask:
   - Monthly minimums, per-release fees, and the revenue share they keep
   - Which stores they reach (Spotify, Apple, Amazon, YouTube Content ID, TikTok/SoundOn, Meta, Tencent, Anghami, Boomplay)
   - **Intake method**: DDEX ERN over SFTP/S3 (plug straight into this code), or a REST API (write a small adapter)
   - Report format and timing (monthly CSV? DSR?) and payment terms (net 30/60/90)
   - White-label: can artists never see the vendor's brand?
   - Fraud tools, Content ID, and pre-save/pitching support
2. **Add the backend as a delivery target** (Admin → Delivery targets). Start in TEST mode.
   - If they take DDEX over SFTP: `sftp` transport, their DPID, and their host key.
   - If they have a REST API: subclass `HTTPTransport.send` in `suprm/delivery/transports.py`
     to match their endpoints.
3. **Deliver 2–3 test releases** and fix anything their QC rejects. Then switch the target to LIVE.
4. **Each month**: download their royalty report and import it (Admin → Royalty imports). Review unmatched lines, click
   Allocate, fund your Stripe balance, then run payouts.

---

## 5. Phase 2+: go direct store by store

Go direct when a store's share of your revenue makes the backend's cut worth
removing, and your catalog is big enough for the store to accept you.

| Step | Work in this repo |
|---|---|
| Apply to the store's content-provider program, sign the agreement, receive SFTP/S3 credentials and their DPID | Add a new delivery target with `sftp` or `s3` |
| Test deliveries against the store's spec | Adjust `suprm/ddex/ern.py` for store-specific fields; validate with the DDEX Workbench validator |
| Handle **acknowledgements** (the store tells you whether ingestion succeeded) | **To build:** poll the store's ACK folder and update `Delivery.status` |
| Import **DDEX DSR sales reports** (large files, sometimes hundreds of MB) | **To build:** a streaming DSR parser feeding the same `RoyaltyLine` table |
| Move the store's traffic off the backend | Deliver an update to the direct target, then a takedown to the backend for that store only (coordinate the timing with both) |

Stores usually worth going direct to first: **Spotify, Apple Music, Amazon Music, YouTube**.
Together they are typically most of a distributor's revenue.

---

## 6. How Suprm Sounds can beat TuneCore and DistroKid

Features the platform already supports or makes easy:
- **Splits that pay people before they sign up.** The money waits under their email.
- **Transparent ledger.** Every fraction of a cent, by store, country and track.
- **QC before submitting.** The artist sees exactly what a store would reject, before it's rejected.
- **Artist-friendly pricing.** `PLATFORM_COMMISSION_PERCENT` can be 0 (charge a subscription instead) or any rate.

Ideas for the roadmap:
- Pre-save / smart-link pages generated for each release
- Advances based on earnings history (much later; needs capital and underwriting)
- Split sheets signed inside the app (e-signature) before release
- Built-in sync-licensing pitch catalog
- Artist community (Discord) with release-day promo swaps

---

## 7. Technical to-do before real artists and money

Done:
- [x] Postgres support with Alembic migrations (`suprm migrate`), tested on Postgres 16
- [x] Media on S3 or Cloudflare R2 (`STORAGE_BACKEND=s3`) with private, short-lived download links
- [x] Password reset and email verification (console, SMTP or Resend)
- [x] Background worker for deliveries (`suprm worker`), with retries and backoff
- [x] Two-factor login (TOTP), required for admins
- [x] Legal pages, with acceptance recorded at sign-up (`LEGAL_VERSION`)

Still to do:

| Priority | Item |
|---|---|
| Must | Validate ERN output with DDEX Workbench and your backend's spec before going LIVE |
| Must | Attorney review of the four legal drafts in `suprm/legal/` |
| Should | Vendor-specific backend adapter once you've picked one |
| Should | Audit log of admin actions |
| Should | DDEX ACK processing and DSR parser (Phase 2) |
| Should | Multi-currency reports (convert to USD at statement FX rate on import) |
| Nice | Loudness and silence checks on audio (ffmpeg), artwork text/logo checks |

The step-by-step setup (IDs, Stripe, backend outreach emails, hosting) is in [`SETUP_GUIDE.md`](SETUP_GUIDE.md).
