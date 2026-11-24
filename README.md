# ⚡ ApplyKit — AI Job Toolkit Hub for Africa + Global Freelancers

ApplyKit is a mobile-first, SEO-optimized **AI Career & Freelance Toolkit Hub** combining:
1. **Micro-Tool Website (`/web`)** — Python 3.11 + FastAPI + Jinja2 + TailwindCSS + Vanilla JS serving **7 public SEO Showcase Tools** + **59+ Hidden Vault Tools** summoned on-the-fly via the universal `"⚡ Ask ApplyKit..."` command palette (`⌘K`).
2. **Multi-Browser Extension (`/extension`)** — WXT + React + TypeScript + `webextension-polyfill` (Manifest V3) compiling from one codebase for **Chrome, Edge, Brave, Opera, and Firefox** with floating in-page job overlays on Upwork & LinkedIn.
3. **Single Backend, Database & Free AI Layer** — Supabase (Postgres + Google OAuth + RLS + CV Storage), Groq (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`) with automatic OpenRouter fallback, Safaricom Daraja **M-Pesa STK Push (750 KES/mo)** + Manual Till fallback, and **Lemon Squeezy ($6/mo & $29 lifetime)** global checkout.

---

## Monorepo Structure

```text
/Applykit
├── supabase/
│   └── schema.sql                  # Full Postgres schema, triggers, Storage bucket & RLS policies
├── web/                            # FastAPI HTML + JSON API Backend
│   ├── main.py                     # FastAPI app, strict CORS, CSP/HSTS headers, SlowAPI rate limiter
│   ├── requirements.txt            # Pinned Python 3.11 dependencies
│   ├── .env.example                # Server-side environment variable template (never commit .env!)
│   ├── render.yaml & Procfile      # 1-click Render.com free tier deployment
│   ├── ads.txt                     # IAB Google AdSense authorized seller file
│   ├── lib/
│   │   ├── ai_client.py            # Groq primary -> OpenRouter 429/500 auto-fallback + 24h SHA-256 cache
│   │   ├── prompts.py              # XML delimiter prompt-injection guards
│   │   ├── router.py               # Keyword -> Platform Context -> Groq 8B fallback universal router
│   │   ├── dynamic_runner.py       # On-the-fly Hidden Vault tool execution engine
│   │   ├── limits.py               # Strict Free (1 anon / 5 logged / 20 Kanban) vs Pro enforcement
│   │   ├── mpesa.py                # Safaricom Daraja OAuth cache + Lipa Na M-Pesa STK Push
│   │   ├── security.py             # python-jose JWT verifier, CSP/HSTS middleware, PDF/DOCX <=2MB validator
│   │   └── supabase_client.py      # Service-role DB client + local dev fallback store
│   ├── tools/registry.json         # 7 visible showcase tools + 59 hidden vault tools (66 total)
│   ├── routes/                     # pages.py, api_ai.py, api_router.py, api_apps.py, api_payments.py
│   ├── templates/                  # base.html, index.html, dashboard.html, pricing.html, admin.html, tools/*
│   └── static/                     # app.js + style.css
└── extension/                      # WXT Multi-Browser Extension (Chrome, Edge, Firefox, Opera)
    ├── wxt.config.ts
    ├── package.json
    ├── lib/api.ts
    └── entrypoints/                # background.ts, upwork.content.ts, linkedin.content.ts, widget.content.tsx, popup/
```

---

## 1. Quick Local Run (`< 60 seconds`)

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open **`http://localhost:8000`**:
- Homepage displays **only the 7 Showcase Tools** + `"⚡ Ask ApplyKit..."` search bar.
- Press **`⌘K` / `Ctrl+K`** and type `"resign"`, `"NDA"`, `"negotiate"`, or `"loom"` to summon and run **Hidden Vault Tools** on-the-fly without dedicated pages.
- Run automated tests:
  ```bash
  cd web && pytest -v
  ```

---

## 2. Free AI Keys Setup (Groq Primary + OpenRouter Fallback)

1. **Groq (Primary — Free):**
   - Sign up at [https://console.groq.com/keys](https://console.groq.com/keys) and generate an API key (`gsk_...`).
   - Add `GROQ_API_KEY=gsk_...` to `web/.env`.
   - Pro users automatically run `llama-3.3-70b-versatile`; Free users run ultra-fast `llama-3.1-8b-instant`.
2. **OpenRouter (Zero-Downtime Fallback — Free Models):**
   - Sign up at [https://openrouter.ai/keys](https://openrouter.ai/keys) and create a key (`sk-or-v1-...`).
   - Add `OPENROUTER_API_KEY=sk-or-v1-...` to `web/.env`.
   - Whenever Groq returns HTTP `429` or `5xx`, `lib/ai_client.py` automatically switches to `meta-llama/llama-3.3-70b-instruct:free` and `mistralai/mistral-7b-instruct:free`.

---

## 3. Supabase Database, Google OAuth & RLS Setup

1. Create a free project at [https://supabase.com](https://supabase.com).
2. Open **SQL Editor → New Query**, paste the entire contents of [`supabase/schema.sql`](supabase/schema.sql), and click **Run**. This creates:
   - `profiles`, `applications`, `ai_usage_logs`, `search_logs`, `mpesa_transactions`, `payment_webhooks`, `referrals`
   - Automatic `on_auth_user_created` profile trigger
   - Strict **Row Level Security (`auth.uid() = user_id`)** on every user table
   - Private `cvs` Storage bucket capped at `2MB` (`application/pdf` & `.docx` only)
3. Enable **Google OAuth**:
   - In Supabase **Authentication → Providers → Google**, paste your Google Cloud OAuth Client ID & Secret and set the Redirect URL shown by Supabase.
   - Under **Authentication → URL Configuration**, add `http://localhost:8000/dashboard` and your Render production URL.
4. Copy keys from **Project Settings → API** into `web/.env`:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY` (safe public key for browser OAuth)
   - `SUPABASE_SERVICE_KEY` (**backend `.env` only — never expose!**)
   - `SUPABASE_JWT_SECRET` (used by `python-jose` to verify Bearer tokens on `/api/*`)

---

## 4. Safaricom Daraja M-Pesa Setup (Sandbox → Production Cashflow)

1. Log in to [https://developer.safaricom.co.ke](https://developer.safaricom.co.ke) and create an app with **Lipa Na M-Pesa Sandbox** enabled.
2. Copy your **Consumer Key** and **Consumer Secret** into `web/.env`:
   ```ini
   MPESA_ENV=sandbox
   MPESA_CONSUMER_KEY=your_key
   MPESA_CONSUMER_SECRET=your_secret
   MPESA_SHORTCODE=174379
   MPESA_PASSKEY=bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919
   MPESA_CALLBACK_URL=https://your-service.onrender.com/api/payments/mpesa/callback
   MPESA_MANUAL_TILL=4182930
   ```
3. **Going Live (Production):**
   - Complete **Go Live** on the Daraja Portal using your Safaricom Paybill or Buy Goods Till (`Store Number` + `Head Office Shortcode`).
   - Switch `MPESA_ENV=production`, update `MPESA_SHORTCODE` and your production `MPESA_PASSKEY` emailed by Safaricom, and verify `MPESA_CALLBACK_URL` points to your HTTPS Render URL.
4. **Manual Till Fallback & Admin Panel:**
   - Users who miss the STK prompt can pay to `MPESA_MANUAL_TILL` on `/pricing` and submit their confirmation code.
   - Visit `/admin` (protected by `ADMIN_USERNAME` and `ADMIN_PASSWORD` HTTP Basic Auth) to approve Till codes or toggle Pro by email in 1 click.

---

## 5. Google AdSense Approval & Monetization Setup

1. Replace `pub-XXXX` in **`web/ads.txt`** with your publisher ID:
   ```text
   google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0
   ```
2. Set `ADSENSE_CLIENT_ID=ca-pub-1234567890123456` in `web/.env` (or Render Environment Variables).
3. Submit your live domain in Google AdSense:
   - All 7 `/tools/*` pages ship semantic HTML, `<1s` mobile load, unique `<title>` + meta descriptions, `FAQPage` JSON-LD schema, `/sitemap.xml`, `/robots.txt`, `/privacy` AdSense cookie disclosure, and a Kenya DPA / GDPR consent banner.
   - Invalid-click protection is built-in: max 3 ad slots per page, `>=160px` vertical margin from primary CTA buttons, and automatic ad removal (`{% if not user.is_pro %}`) for Pro subscribers.

---

## 6. Deploy Backend + Web to Render.com (Free Tier)

1. Push this repository to GitHub.
2. In [https://dashboard.render.com](https://dashboard.render.com), click **New + → Blueprint** and select your repo (Render automatically reads `web/render.yaml`).
   - Or choose **New Web Service**, set **Root Directory** to `web`, **Build Command** to `pip install -r requirements.txt`, and **Start Command** to `uvicorn main:app --host 0.0.0.0 --port $PORT`.
3. Add the secret environment variables from `web/.env.example` in Render's **Environment** tab and set `BACKEND_URL=https://your-app.onrender.com`.

---

## 7. Build & Publish Multi-Browser Extension (Chrome, Edge, Brave, Opera, Firefox)

```bash
cd extension
npm install

# Production builds per browser target:
npm run build -- --browser chrome    # Outputs .output/chrome-mv3 (Chrome & Brave)
npm run build -- --browser edge      # Outputs .output/edge-mv3
npm run build -- --browser firefox   # Outputs .output/firefox-mv3
npm run build:opera                  # Outputs .output/opera-mv3

# Create store-ready ZIP archives:
npm run zip:all
```

### Store Publishing Steps:
- **Chrome Web Store (& Brave):** Upload `.output/chrome-mv3-*.zip` at [Chrome Developer Dashboard](https://chrome.google.com/webstore/devconsole). Justify `storage` (saving JWT/CV snippet) and `activeTab` / host permissions (`upwork.com`, `linkedin.com`).
- **Microsoft Edge Add-ons:** Upload `.output/edge-mv3-*.zip` at [Edge Partner Center](https://partner.microsoft.com/dashboard/microsoftedge) (free developer registration).
- **Firefox Add-ons (AMO):** Upload `.output/firefox-mv3-*.zip` at [addons.mozilla.org/developers](https://addons.mozilla.org/developers/). Manifest includes `browser_specific_settings.gecko.id` (`extension@applykit.africa`) and uses a floating in-page widget instead of Chrome-only `sidePanel`.

---

## 8. Security Checklist

- [x] `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `SUPABASE_SERVICE_KEY`, `MPESA_CONSUMER_SECRET`, and `LEMONSQUEEZY_WEBHOOK_SECRET` stay strictly server-side in `.env`.
- [x] Every authenticated `/api/*` request verifies `Authorization: Bearer <JWT>` via `python-jose`.
- [x] PostgreSQL Row Level Security (`RLS`) enabled on all tables + private `cvs` Storage bucket.
- [x] `slowapi` rate limits enforced: `10/min/IP` on AI endpoints, `3/hour/IP` on M-Pesa STK push, `60/min/IP` on router.
- [x] Strict CORS (`BACKEND_URL` + `chrome-extension://` + `moz-extension://`, no wildcard credentials) + `CSP`, `HSTS`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- [x] Pydantic max-length bounds (`15,000` chars), Jinja2 auto-escaping, PDF/DOCX magic-byte & `<=2MB` upload check, and `^254[17]\d{8}$` phone validation.
- [x] Prompt-injection XML delimiters (`<UNTRUSTED_CV>`, `<UNTRUSTED_JD>`) + forced JSON validation + 24h input-hash cache + zero raw CV logging.
- [x] Lemon Squeezy HMAC-SHA256 webhook verification + Safaricom callback IP check + 1-click **Delete My Data** (Kenya DPA & GDPR).
