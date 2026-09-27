# 10 — Estimated Third-Party API & Infrastructure Costs

> **Read this first.** LLM prices come from Anthropic's published per-token rates as of mid-2026. Other vendor prices are **approximate list prices from general knowledge and must be re-checked on each vendor's pricing page before budgeting.** Conversion uses **₹88 / USD** (an assumption). Figures exclude GST on vendor invoices (18 % where applicable, often claimable as ITC).

## 10.1 LLM (Anthropic Claude API)

| Model (tier) | Input $/1M tok | Output $/1M tok | Notes |
|---|---|---|---|
| `claude-haiku-4-5` (fast) | 1.00 | 5.00 | |
| `claude-sonnet-5` (standard) | 2.00 | 10.00 | |
| `claude-opus-5` (deep) | 5.00 | 25.00 | |

Modifiers: prompt-cache **reads ≈ 0.1×** input price (writes 1.25× for the 5-minute TTL). **Batch API ≈ 50 %** off for non-interactive jobs.

### Per-operation estimates

Token counts are design assumptions. They will be replaced with measured values from `ai_generations` after the first 1,000 real calls.

| Operation | Model | Input tokens | Output tokens* | ≈ USD / call | ≈ ₹ / call |
|---|---|---|---|---|---|
| AI Estimate extraction (short, 1–2 components) | Haiku 4.5 | 3,000 (2,500 cached) | 900 | 0.0055 | 0.50 |
| AI Estimate extraction (typical, 3–8 components) | Sonnet 5 | 3,500 (2,500 cached) | 1,800 | 0.021 | 1.9 |
| Same, with one validation retry | Sonnet 5 | ×2 | ×2 | 0.042 | 3.7 |
| Item description draft | Haiku 4.5 | 800 | 200 | 0.002 | 0.18 |
| Assistant question (P2) | Sonnet 5 | 10,000 | 800 | 0.028 | 2.5 |
| Document BOQ extraction, **per page** (P2) | Opus 5 | 3,000 | 700 | 0.033 | 2.9 |
| 20-page BOQ PDF (P2) | Opus 5 | 60,000 | 14,000 | 0.65 | 57 |
| Drawing analysis, per sheet (P3) | Opus 5 | 5,000 | 1,500 | 0.06 | 5.3 |

\* Output tokens include model reasoning, which is billed as output.

**Takeaway:** interactive AI estimates are cheap (₹0.5–4 each). **Document analysis is 15–30× more expensive per action** and must be metered separately (a `doc_pages` quota per plan), not counted as one "AI generation".

### Monthly LLM cost per subscriber (worst case = full quota used)

| Plan | Price | AI generations | Doc pages (proposed) | Worst-case LLM cost | % of revenue |
|---|---|---|---|---|---|
| Free | ₹0 | 5 | 0 | ≈ ₹20 | — (acquisition cost) |
| Starter | ₹499 | 50 | 0 | ≈ ₹190 | 38 % worst case, ≈ 10–15 % typical |
| Pro | ₹999 | 300 ("higher limits") | 100 | ≈ ₹1,100 + ₹290 = ₹1,400 | **over 100 % if fully used** |
| Business | ₹2,999 | 1,000 pooled | 400 | ≈ ₹3,700 + ₹1,160 | **over 100 % if fully used** |

Recommendations (not yet decided):
1. Replace "unlimited" with explicit, generous caps. Suggested values: Pro 200 generations + 50 doc pages. Business 750 pooled + 200 doc pages. Sell top-up packs.
2. Default to Haiku-first routing with escalation, and measure how often escalation happens.
3. Make heavy use of the response cache and prompt cache.
4. Re-check the margin once real usage data exists (month 2).

## 10.2 OCR (Phase 2)

| Option | Approx. cost | Notes |
|---|---|---|
| Tesseract (self-hosted, `eng+tel+hin`) | infra only | Free. Weaker on scans and tables. Good enough to start |
| AWS Textract (text detection) | ≈ $1.50 / 1,000 pages; tables/forms much higher | Mumbai region available |
| Google Document AI (OCR) | ≈ $1.50 / 1,000 pages | good Indic-script support |
| Claude vision directly on page images | included in the per-page LLM cost above | can replace a separate OCR step for BOQ extraction. Compare quality on the eval set |

## 10.3 Payments

| Item | Approx. cost |
|---|---|
| Razorpay standard pricing | ≈ 2 % per domestic transaction (cards/UPI/net banking) + 18 % GST on the fee. Subscriptions/UPI AutoPay may carry different fees, so verify |
| At ₹999/month | ≈ ₹20 + ₹3.6 GST ≈ ₹24 per payment |

## 10.4 Infrastructure (early stage, up to ~500 paying users)

| Component | Suggested | Approx. monthly |
|---|---|---|
| Frontend hosting | Vercel Pro (1 seat) | $20 |
| API + 1 worker containers | Render / Railway / Fly.io, or AWS ECS Fargate (2 × 0.5 vCPU / 1 GB) | $30–60 |
| PostgreSQL (managed, Mumbai) | Neon / Supabase / RDS db.t4g.small | $25–50 |
| Redis | Upstash / ElastiCache small | $10–20 |
| Object storage | S3 ap-south-1 or Cloudflare R2 (≈ $0.015/GB-month, no egress fees) | < $5 at start |
| Malware scanning | ClamAV container | included above (≈ 1 GB RAM) |
| Email | AWS SES (≈ $0.10 / 1,000 emails) or Resend free tier | < $5 |
| Error monitoring | Sentry Developer/Team | $0–26 |
| Domain + DNS | .in domain, Cloudflare DNS | ≈ ₹1,000 / year |
| **Total fixed** | | **≈ $120–190 / month (₹10,500–16,700)** |

**Break-even on fixed infrastructure** is about 25–40 Starter subscribers (≈ ₹425 net each after payment fees and typical LLM use). LLM and payment costs are variable and scale with usage (§10.1, §10.3).

## 10.5 Development-time costs

* LLM eval runs: 60 golden cases × ~₹2 ≈ ₹120 per full eval run on Sonnet 5. Budget ₹5,000/month during active prompt development.
* Anthropic workspace spend limits and a separate key per environment (dev / staging / prod / eval).
