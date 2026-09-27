# 09 — Required Environment Variables

All secrets live in the deployment platform's secret store and are injected as environment variables. `.env.example` lists every key with a placeholder. The **only** variables exposed to the browser are those prefixed `NEXT_PUBLIC_`, and none of them is secret.

## 9.1 Backend (API + workers)

| Variable | Req. | Example / default | Notes |
|---|---|---|---|
| `APP_ENV` | ✔ | `development` \| `staging` \| `production` | |
| `APP_BASE_URL` | ✔ | `https://app.estimateai.in` | used in emails and OAuth redirects |
| `API_CORS_ORIGINS` | ✔ | `https://app.estimateai.in` | comma-separated |
| `LOG_LEVEL` | | `INFO` | |
| `SECRET_KEY` | ✔ 🔒 | 64 random bytes | CSRF and signing of misc tokens |
| `JWT_SIGNING_KEY` | ✔ 🔒 | Ed25519 private key (PEM) | EdDSA JWT. Rotate with `JWT_SIGNING_KEY_PREVIOUS` |
| `JWT_SIGNING_KEY_PREVIOUS` | | | verification-only during rotation |
| `ACCESS_TOKEN_TTL_SECONDS` | | `900` | |
| `REFRESH_TOKEN_TTL_DAYS` | | `30` | |
| `COOKIE_DOMAIN` | ✔ | `.estimateai.in` | |
| `DATABASE_URL` | ✔ 🔒 | `postgresql+psycopg://user:pass@host:5432/estimateai?sslmode=require` | |
| `DATABASE_POOL_SIZE` | | `10` | |
| `REDIS_URL` | ✔ 🔒 | `rediss://…` | Celery broker, cache, rate limiter |
| `CELERY_RESULT_BACKEND` | | `$REDIS_URL` | |
| `S3_ENDPOINT_URL` | | empty for AWS; `http://minio:9000` locally; R2 endpoint | |
| `S3_REGION` | ✔ | `ap-south-1` | |
| `S3_BUCKET_UPLOADS` | ✔ | `estimateai-uploads-prod` | private |
| `S3_BUCKET_EXPORTS` | ✔ | `estimateai-exports-prod` | private, lifecycle-expire after 30 d |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | ✔ 🔒 | | prefer an IAM role in AWS |
| `SIGNED_URL_TTL_SECONDS` | | `300` | |
| `MAX_UPLOAD_MB_DEFAULT` | | `25` | plan limits can lower or raise it |
| `CLAMAV_HOST` / `CLAMAV_PORT` | ✔ (P2) | `clamav` / `3310` | |
| `ANTHROPIC_API_KEY` | ✔ 🔒 | | backend and workers only |
| `AI_MODEL_FAST` | | `claude-haiku-4-5` | router tier |
| `AI_MODEL_STANDARD` | | `claude-sonnet-5` | |
| `AI_MODEL_DEEP` | | `claude-opus-5` | |
| `AI_REQUEST_TIMEOUT_SECONDS` | | `120` | |
| `AI_MAX_INPUT_CHARS` | | `4000` | description cap (plan-dependent override) |
| `AI_PRICE_TABLE_JSON` | | `{"claude-haiku-4-5":[1,5],"claude-sonnet-5":[2,10],"claude-opus-5":[5,25]}` | USD per 1M tokens (in, out), for cost ledger. Keep in sync with the provider's price page |
| `AI_RESPONSE_CACHE_TTL_HOURS` | | `168` | |
| `OCR_PROVIDER` | (P2) | `tesseract` \| `aws_textract` \| `google_docai` | |
| `OCR_TESSERACT_LANGS` | | `eng+tel+hin` | |
| `AWS_TEXTRACT_REGION` | (if used) | `ap-south-1` | credentials via IAM role |
| `GOOGLE_DOCAI_PROCESSOR_ID`, `GOOGLE_APPLICATION_CREDENTIALS` | (if used) 🔒 | | |
| `GOOGLE_OAUTH_CLIENT_ID` | ✔ | | |
| `GOOGLE_OAUTH_CLIENT_SECRET` | ✔ 🔒 | | |
| `GOOGLE_OAUTH_REDIRECT_URI` | ✔ | `https://app.estimateai.in/api/v1/auth/google/callback` | |
| `RAZORPAY_KEY_ID` | ✔ | `rzp_live_…` | public; also sent to the browser via the API |
| `RAZORPAY_KEY_SECRET` | ✔ 🔒 | | server-side API calls |
| `RAZORPAY_WEBHOOK_SECRET` | ✔ 🔒 | | HMAC verification of webhooks |
| `EMAIL_PROVIDER` | ✔ | `ses` \| `smtp` \| `resend` | |
| `EMAIL_FROM` | ✔ | `EstimateAI <no-reply@estimateai.in>` | |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | (if smtp) 🔒 | | |
| `SENTRY_DSN` | | | |
| `RATE_LIMIT_DEFAULT` | | `120/minute` | per user |
| `RATE_LIMIT_AUTH` | | `10/minute` | per IP |
| `RATE_LIMIT_AI` | | `10/minute` | per user, in addition to quota |
| `ADMIN_BOOTSTRAP_EMAIL` | | | first platform admin on initial deploy |

## 9.2 Frontend (Next.js)

| Variable | Req. | Example | Notes |
|---|---|---|---|
| `BACKEND_URL` | ✔ | `https://api.internal.estimateai.in` | server-side only, used by the `/api/*` rewrite |
| `NEXT_PUBLIC_APP_NAME` | | `EstimateAI` | |
| `NEXT_PUBLIC_SENTRY_DSN` | | | public by design |
| `NEXT_PUBLIC_DEFAULT_LOCALE` | | `en-IN` | |
| `SENTRY_AUTH_TOKEN` | (build) 🔒 | | source-map upload in CI only |

The Razorpay key id is fetched from `/billing/checkout` at runtime, so it isn't baked into the build.

## 9.3 CI

`DATABASE_URL` (service container), `REDIS_URL`, and **no** `ANTHROPIC_API_KEY` in the default CI job. LLM-dependent tests use recorded responses. The opt-in eval workflow uses a separate, spend-capped key stored as a protected secret.

🔒 = secret. It must never be logged, committed, or exposed to the frontend.
