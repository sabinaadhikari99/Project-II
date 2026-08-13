# SkillSync AI — Detailed Technical Report

> AI-powered recruitment & career-development platform: ATS-friendly CV generation, skill-gap analysis, AI job matching, interview practice, quiz, chatbot and notifications.

---

## 1. Overview

SkillSync AI is a **Django monolith** that serves a server-rendered Bootstrap frontend plus a full **REST API** (DRF + JWT). AI capabilities are layered on top:

- **Rule-based + statistical AI** (profession classifier, CV signal extraction, weighted match scoring, FAISS semantic search) — runs inside Django.
- **LLM AI** (Google Gemini 2.5 Flash) — for resume insights, chatbot, interview coaching, quiz generation. Falls back to rule-based logic when no API key or on failure.
- **Embedding microservice** (FastAPI + Sentence-BERT) — serves 384-dim embeddings over HTTP; falls back to a local deterministic hash embedding.

```
                        ┌──────────────────────────────────────────────┐
                        │              Browser (Bootstrap 5)           │
                        │  Django templates + fetch/JS (api() helper)  │
                        └───────────────┬──────────────────────────────┘
                                        │ HTTPS (pages) + WebSocket ws/notifications/
                                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                          DJANGO 4.2 (Monolith)                            │
│  config/  (settings, urls, asgi/wsgi)                                     │
│  apps/    accounts · jobs · skillgap · recruiters · admin_panel ·         │
│           chatbot · quiz · cvgen · external · notifications · state ·     │
│           core · shared                                                   │
│  DRF + SimpleJWT · Channels · drf-spectacular (Swagger) · CORS            │
├──────────────┬──────────────────────────────┬─────────────────────────────┤
│ SQLite (db)  │ FAISS vector_store/          │ LocMemCache (state, quiz,   │
│              │ (faiss_index.bin + id_map)   │ skillgap, career context)   │
└──────────────┴──────────────────────────────┴─────────────────────────────┘
        │ HTTP POST /embed/ (1.5s timeout)              │ HTTPS
        ▼                                               ▼
┌──────────────────────────┐                   ┌──────────────────────────┐
│ FastAPI :8001            │                   │ Google Gemini 2.5 Flash  │
│ Sentence-BERT            │                   │ (chatbot, interview,     │
│ all-MiniLM-L6-v2 (384d)  │                   │ quiz, resume insights)   │
└──────────────────────────┘                   └──────────────────────────┘
```

External services: **Apify** (LinkedIn job scraping), **LinkedIn OAuth** (profile import), **Cloudinary** (media storage), **Gmail SMTP** (email). A standalone **Streamlit** prototype (`main.py` + `src/`) demonstrates the AI job-recommender concept.

---

## 2. Technology, Tools, Libraries, Frameworks

### 2.1 Backend stack (`requirements.txt` / `pyproject.toml`)

| Layer | Technology | Version | Role |
|---|---|---|---|
| Web framework | Django | 4.2 | Monolith backend, templates, ORM, admin |
| API framework | Django REST Framework | 3.14 | All `/api/*` endpoints |
| Auth | djangorestframework-simplejwt | 5.3 | JWT access (15 min) + refresh (7 days), rotation, blacklist |
| CORS | django-cors-headers | 4.3 | Cross-origin access |
| API docs | drf-spectacular | ≥0.29 | OpenAPI schema + Swagger UI at `/swagger/` |
| WebSockets | Django Channels | 4.x | Real-time notification push |
| Admin skin | django-jazzmin | ≥3.0 | Styled Django admin |
| Media storage | Cloudinary + django-cloudinary-storage | 1.36 / ≥0.3 | Default file storage backend |
| Config | python-dotenv / python-decouple / django-environ | — | `.env` loading |
| DB | SQLite (built-in) | — | Default database |

### 2.2 AI / ML stack

| Technology | Version | Role |
|---|---|---|
| sentence-transformers | 2.2.2 | `all-MiniLM-L6-v2` embeddings (via FastAPI service) |
| FAISS (faiss-cpu) | 1.7.4 | Vector index of job + profile embeddings (IndexFlatIP) |
| scikit-learn | 1.3.0 | ML utilities in analysis pipeline |
| numpy / pandas | 1.24.3 / 2.0.3 | Vector math, data handling |
| google-generativeai | 0.3.2 | Gemini 2.5 Flash: insights, chatbot, interview, quiz |

### 2.3 Document / scraping / misc

| Technology | Role |
|---|---|
| PyMuPDF (fitz), pypdf, pypdf2 | PDF text extraction (resumes) |
| reportlab | CV generation to PDF (letter size, 10 template styles) |
| python-docx | Installed, currently unused (CV output is PDF-only) |
| Apify (apify-client) | LinkedIn job scraping via actor `hKByXkMQaC5Qt9UMN` |
| requests | HTTP fallback / API calls |
| faker | Synthetic seed data generation |
| FastAPI + uvicorn | Embedding microservice on `:8001` |
| Streamlit | Standalone prototype app (`main.py`) |

### 2.4 Frontend stack

- **Server-rendered** Django templates (37 files) — Bootstrap **5.3.3** + Bootstrap Icons + Geist font (CDN).
- **SPA-style interactivity** — a global `api()` fetch helper (`static/js/app.js`) calls `/api/*` with JWT from `localStorage`, CSRF header, single-flight token refresh, auto-retry, and logout fallback.
- **`static/js/state.js`** — `window.SkillSyncState`: per-user localStorage state (`ss:v1:{owner}:{key}`) synced to `/api/state/ui/` with 900 ms debounce and offline write queue.
- **Chart.js 4.4.1** — score breakdown doughnut charts on the AI-match page.
- No Node.js build step; no framework (no React/Vue).

---

## 3. Application Structure

```
config/            settings, root urls, asgi (WebSocket router), wsgi
apps/
  accounts/        User/UserProfile, JWT auth, LinkedIn OAuth, sessions, global search
  jobs/            JobPosting/Application/SavedJob/RecentlyViewedJob + AI match pipeline
  shared/          FAISS manager, profession classifier, CV signals, specializations,
                   deductions, resume quality, embeddings client, permissions
  state/           Persistent state layer: AnalysisSession, UIState, QuizSession
  skillgap/        Gap analysis, learning roadmap, course recommendations
  chatbot/         AI career assistant + interview practice engine
  quiz/            Gemini-generated technical quiz
  cvgen/           CV builder (10 templates, PDF export)
  recruiters/      Recruiter job postings + candidate matching
  admin_panel/     Admin dashboard APIs (stats, user/report/settings management)
  notifications/   In-app notifications + WebSocket push + email
  external/        LinkedIn job scraping (Apify + mock fallback)
  core/            App signals (auto-embed profiles on save)
  fastapi_microservice/  Embedding HTTP service (FastAPI)
templates/         Server-rendered pages
static/            app.css, app.js, state.js
src/               Standalone prototype helpers (Gemini + Apify) — Streamlit only
vector_store/      faiss_index.bin + id_map.pkl
data/              Synthetic seed datasets (jobs, profiles, courses…)
```

**Custom user model:** `accounts.User` (email is `USERNAME_FIELD`, roles `job_seeker | recruiter | admin`).

---

## 4. Backend — How It Works

### 4.1 Request flow

1. Browser loads a server-rendered page (Django templates; auth pages gated by `LoginRequiredMixin`).
2. Interactive pages call `api(url, opts)` → `fetch` with `Authorization: Bearer <access>`.
3. DRF authenticates via SimpleJWT; permissions enforce roles (`IsJobSeeker`, `IsRecruiter`, `IsAdmin`).
4. On 401, `app.js` refreshes the token (single-flight) and retries once; on failure it logs out.
5. Views return JSON; the page JS renders it into DOM (Bootstrap toasts for feedback).

### 4.2 Authentication & security

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auth/register/` | POST | Create job-seeker/recruiter (admin rejected) |
| `/api/auth/login/` | POST | JWT pair **+** Django session cookie |
| `/api/auth/token/` | POST | Mint JWT for already-authenticated user |
| `/api/auth/refresh/` | POST | Rotate refresh token (blacklist old) |
| `/api/auth/logout/` | POST | Blacklist refresh + flush session + delete cookie |
| `/api/auth/verify/` | POST | Validate access token (login page boot) |
| `/api/auth/profile/` | GET/PATCH | Read/update profile (+ base64 image ≤5 MB) |
| `/api/auth/resume/` | POST | PDF-only CV upload → text extraction + skill merge |
| `/api/auth/change-password/` | POST | Validated password change |
| `/api/auth/sessions/` | GET/DELETE | List / kill other active sessions |
| `/api/auth/linkedin/start·login·callback·role-select·conflict-resolve` | GET/POST | LinkedIn OAuth + conflict handling |

`SaveDeviceInfoMiddleware` parses the User-Agent into `{browser, os, device, created_at}` stored in the session.

### 4.3 Global search

`GET /api/search/?q=` — role-dependent: recruiters search candidates (profile fields, `icontains`), seekers search active jobs (title, company, skills, category). Min 2 chars, top 8 results.

### 4.4 Notifications (WebSocket push)

- `Notification` model with 14 types + priority + `match_percentage`.
- `NotificationConsumer` (`ws/notifications/`) — joins `notifications_{user.id}` group; unauthenticated rejected (4001).
- Django signals: `post_save` on Notification → `channel_layer.group_send`; on JobPosting → notify job-seekers (matched ≥ threshold) + admin; on Application → notify recruiter; on User → admin.
- Email variant `_send_email_async` runs in a daemon thread (Gmail SMTP).

---

## 5. AI / ML — Deep Dive

### 5.1 Embedding pipeline

1. `FASTAPI_URL` (`http://127.0.0.1:8001/embed/`) → Sentence-BERT `all-MiniLM-L6-v2` → 384-dim normalized vector (1.5 s timeout).
2. Fallback: deterministic SHA-256 hash-bucket 384-dim vector (never fails).
3. **Writers:** job postings embed `embedding_text` (title+company+location+mode+category+description+skills+experience+education) on create/update (`create_job_with_embedding`); user profiles auto-embed on every save via `apps/core/signals.py` (name+skills+resume_text+education+experience).
4. **Store:** `FAISSManager` (`apps/shared/vector_db.py`) — `IndexFlatIP` + `id_map.pkl`; prefixes `job:` / `profile:`; process-wide singleton with RLock; `refresh_if_stale()` reloads when another process writes; self-heals map/index desyncs; O(n) rebuild-in-place updates.
5. **Readers:** job recommendations (hybrid rank), semantic fallback, recruiter candidate search (`match_candidates_for_job`).

### 5.2 Profession & specialization classification (rule-based)

- **17 professions** (`PROFESSION_CONFIGS`): weighted skill dictionaries + title lists, ~150 skill synonyms, related-profession graph (`RELATED_PROFESSIONS`).
- `classify_profession_with_resume` — weighted scoring across CV sections (`SECTIONS_WEIGHTS`: title 50, summary 15, experience 15, skills 15, projects 5); low score → fallback; close margin → title/skills 60/40 blend.
- **48 specializations** under the professions (Flutter, React, AI Engineer, SOC Analyst…), detected with `signal_pct*0.6 + title*0.4`, never contradicting the coarse profession.

### 5.3 CV signal extraction (`cv_signals.py`)

Structured parse of resume text: experience years (regex + date-span inference, capped 45), education rank (diploma→PhD 0–4), project/cert counts, metrics/leadership/achievements, open-source/hackathon/awards/research flags, GitHub/portfolio links, action verbs, bullets, word count, section presence (6 expected sections), contact info.

### 5.4 The AI Match score — `compute_match_score`

Weights (settings + fallbacks; effective total 110):

| Component | Weight | Formula (score 0–100) |
|---|---|---|
| Profession | 40 | exact=1.0 · related=0.6 · unknown=0.5 · else 0 |
| Skills | 30 | `covered / required` (confidence-weighted from section provenance) |
| Experience | 15 | ratio curves depending on user vs job years |
| Education | 10 | rank-compare curve (job rank 0 → `0.55+0.1·user`) |
| Semantic | 5 | clipped FAISS cosine similarity |
| Projects | 6 | count (capped 3, 0.25 each) + portfolio/metrics/leadership bonuses |
| Certifications | 4 | count capped 3 × 0.4 |

```
base_score   = Σ(component × weight) / Σweights        (clamped 1–100)
final_score  = base_score − Σ deductions                (≤ 15 pts, capped)
```

**Deductions** (`deductions.py`): severity tariffs critical 5 / medium 3 / minor 2 / trivial 1, capped at 15; critical skills named in the job title or catalogue weight ≥9. **Strengths** ledger built alongside (max 8). Everything returned as an explainable `match_explanation` (why matched / why not higher).

### 5.5 Recommendation pipeline — `recommend_jobs_for_user`

1. Classify profession (resume-based hybrid or skills-based).
2. No profession → semantic-only fallback (FAISS search all jobs + full score).
3. Else: specialization + related professions → candidate pool by `job_category`; widen with adjacent parents if empty; else semantic fallback.
4. Hybrid ranking: FAISS top-k (≤40) + `compute_match_score` per candidate + sort.
5. Thresholds: `AI_MATCH_THRESHOLD=70` (match status), `AI_MATCH_NOTIFICATION_THRESHOLD=80` (fires `notify_job_match`).

### 5.6 Resume analysis — `analyze_resume_match` (2-stage durability)

- **Stage 1 (never lost):** PDF text extraction (≥80 chars) → skill extraction/merge → save file + `cv_url` → profile save.
- **Stage 2 (best-effort):** skill provenance → profession → recommendations → specialization → CV signals → **Gemini insights** (2.5 Flash, temp 0.35, strict JSON, per-specialization relevance; falls back to rule-based summary/insights/suggestions) → resume quality report → skill action plan → structured insights. Failure returns `success=False, cv_saved=True` — CV is never lost.
- Result persisted to `AnalysisSession` (state app) keyed by CV **SHA-256 fingerprint**; `GET /api/jobs/ai-match/` and `/api/state/bootstrap/` restore it — **never re-run the AI**.

### 5.7 Resume quality & action plan

- `resume_quality.py`: weighted ATS report (sections 20, keywords 20, achievements 18, action verbs 12, contact 10, projects 10, formatting 10); bands excellent ≥85 / good ≥70 / fair ≥50.
- `build_skill_action_plan`: demand-counts missing skills across recommendations → importance High ≥60% / Medium ≥30%; difficulty from catalog (2/4/8 weeks); `expected_score_gain` per skill.

---

## 6. Feature Workflows (End-to-End)

### 6.1 Job seeker — AI Match (`/ai-match/`, `recommendations.html`)

1. Upload CV (drag & drop) → `POST /api/jobs/ai-match/` (FormData).
2. Backend runs §5.6; returns profession, specialization, match scores, skills, insights, quality, CV signals, score breakdown, action plan.
3. Page renders skeletons → doughnut charts (Chart.js) → ATS quality report → action-plan cards.
4. Result cached in `AnalysisSession` + `SkillSyncState.cache` (fingerprint-keyed); reloads restore instantly.
5. Notification `resume_analysis_complete` fired; job matches ≥80% notify as they're created.

### 6.2 Job discovery (`/jobs/`)

- `GET /api/jobs/filter/?title=&skill=&experience=&work_mode=` — pairwise skill AND-combinations, synonym normalization.
- `GET /api/jobs/recommended/` — same recommender as AI match.
- Save toggle (`/saved/`), recently viewed (`/recent/`, `/viewed/<pk>/`).
- Apply: `POST /api/jobs/apply/<pk>/` → `Application` row (unique job+applicant) → email to candidate + notification to recruiter.
- Statuses: submitted → reviewing → shortlisted → rejected / hired.

### 6.3 Skill Gap (`/skillgap/`)

1. `GET /api/skillgap/` — builds `CareerContext` from the stored analysis (fingerprint-validated, `?refresh=1` forces recompute; memoized + cached 24 h).
2. Gap universe: **top-3 matched jobs' required skills + specialization core skills** (GAP_JOB_LIMIT=3, pool ≤100).
3. Importance = profession-config weight or `round(3 + share·7)`; floor 8 for top-required, 7 for core; priority High ≥8 or share ≥0.5.
4. Gap categories: critical / important / optional / future; coverage metrics (current skill, missing skill, industry readiness, job readiness); career level from years (<2 junior, ≤5 mid, else senior).
5. `GET /api/skillgap/courses/` — top 5 courses per gap from the course catalog (provider URLs per profession: LinkedIn/edX/Udemy/Coursera).
6. `GET /api/skillgap/roadmap/` — phased plan: `MAX_STEPS=25`, phase size 3, ≤5 skill phases, capstone phase, junior 1.2 / mid 1.0 / senior 0.85 level factors, `SKILLGAP_WEEKLY_HOURS=5`.
7. `GET /api/skillgap/roadmap/progress/` — mark steps not_started/in_progress/completed.

### 6.4 Chatbot (`/chat/`)

1. `GET /api/chatbot/conversation/` → restore active `Conversation` (memory JSON, last 8 turns).
2. `POST /api/chatbot/ask/` → `CareerAssistant.ask()` pipeline:
   **route → remember → retrieve → prompt → generate → format**
   - Route: intent classifier (`intents.py`) — 8 conversational intents (greeting, gratitude, small talk, farewell, identity, encouragement…) + 14 career intents (job_fit, score_explain, skills_next, cv_review, seniority, courses, roadmap, applications, saved_jobs, interview, cover_letter, compare, market, quiz, portfolio, platform) with regex patterns, follow-up inheritance (bare "Why?"), priority ranking.
   - Remember: `ConversationMemory` (max 6 topics, focus job tracking).
   - Retrieve: `CareerContextBuilder` — 11 sections of user/job data (finds jobs, matches, gaps).
   - Generate: Gemini 2.5 Flash via `build_model()` (system-instruction workaround for pinned SDK); temp 0.9 conversational / 0.35 career; offline rule-based grounded answers when Gemini unavailable.
   - Format: `formatter.py` polishes output.
3. Starter suggestions endpoint; `Conversation` / `ChatMessage` persist with `context_used`, `suggestions`, `intent`.

### 6.5 Interview practice (`/interview-practice/`)

1. `POST /api/chatbot/interview/session/` — options: questions 5–15 (default 8), duration 0–60 min, level, interview type (categories per type).
2. `GET session` → question bank (Gemini-generated `generate_bank`), `POST answer/<pk>/` → `evaluate_answer` (score + strengths/weaknesses/coaching/better answer), `POST complete/` → `build_report` (overall/technical/HR/behavioral/communication/confidence).
3. `InterviewTurn` unique per session+question; `InterviewReport` persisted; readiness assessment with weights; sessions history endpoint; reset.
4. Timer + esc-escaped rendering on the page; autosave via state layer.

### 6.6 Quiz (`/quiz/`)

1. `GET /api/quiz/` — restore saved `QuizSession` if fingerprint matches, else generate.
2. Generation (`quiz/utils.py`): Gemini "expert technical interviewer" prompt → exactly 10 MCQs (4 options each, `difficulty` field) **resume-topics-only**, strict JSON; validation (10 q, 4 options, answer ∈ options), difficulty normalized to 4 easy/3 medium/3 hard, max 3 attempts, error map 504/429/503.
3. `POST /api/quiz/progress/` — autosave answers (revision-bumped).
4. `POST /api/quiz/submit/` — server-side scoring (correct answers never leave the server), percentage, results JSON.
5. `POST /api/quiz/reset/`. Cache TTL 1 h; fingerprint invalidates on new CV.

### 6.7 CV Builder (`/cvgen/`)

1. **Create profile** — JobSeekerProfile + Education/Project/Additional formsets (inlineformset_factory).
2. **Choose template** — gallery of 10 styles (modern, professional, minimal, executive, creative, elegant, corporate, ats_friendly, classic, compact) across 3 layouts (single/sidebar/banded).
3. **Preview** — live-rendered HTML mirroring the PDF builder's layout logic.
4. **Generate** — reportlab letter-size PDF; template registry (`cv_templates.py`) drives both PDF and preview for visual parity (fonts, heading styles, dividers, accent colors).

### 6.8 Recruiter (`/dashboard/recruiter/`)

- `POST /api/recruiter/jobs/` → creates job + embedding + FAISS index (taxonomy auto-classified); `PUT` re-embeds.
- `GET /api/recruiter/jobs/` — my postings; `GET /api/recruiter/jobs/<pk>/candidates/` — FAISS `profile:` search → ranked candidates with match scores.
- Applications review → status changes fire `notify_*` + email (`applicant_shortlisted`, `interview_scheduled`, `applicant_status_change`).
- `RecruiterActivity` logs 7 activity types; recruiter dashboard endpoints (`/api/recruiter/dashboard/`).

### 6.9 Admin panel (`/dashboard/admin/`)

- `/api/admin/users/` CRUD, `/api/admin/reports/` (users_by_role, total_jobs, active_jobs, total_applications, applications_by_status), `/api/admin/settings/` (SystemSetting key/value), platform stats.

### 6.10 LinkedIn jobs (`/linkedin/`)

- `GET /api/external/linkedin/?query=&location=` → `fetch_linkedin_jobs` (Apify actor with proxy; mock-data fallback) → normalized `{title, company, location, link}` list. PerformanceTimer logs latency.
- LinkedIn OAuth import: start → consent → callback → userinfo → create user (random 32-hex password) or conflict page → role select / conflict resolve.

### 6.11 Persistent state layer (`/api/state/`)

- `AnalysisSession` (OneToOne user; fingerprint-keyed payload snapshot), `UIState` (namespaced key/value + revision), `QuizSession` (server-side answers).
- `GET /api/state/bootstrap/` — one-call page restore (analysis summary + UI keys + quiz header + fingerprint + has_resume).
- `UIState` writes: `set_many` bulk, 256 KB guard, `select_for_update`, cache invalidated on write, LocMemCache TTL 900 s.
- Frontend `state.js` mirrors this offline with debounced sync (900 ms).

---

## 7. Data Flow Summary

```
CV upload ──► extract text ──► skills ──► profile ──► auto-embed (core signals)
                                          │
                          profession (classifier) ──► specialization ──► CV signals
                                          │
                              recommend_jobs_for_user
                          ┌───────────────┴───────────────┐
                          │  FAISS job:<id> semantic scores │
                          └───────────────┬───────────────┘
                              compute_match_score (7 weighted components)
                                          │
                          deductions.py (final = base − deductions, ≤15)
                                          │
                          Gemini insights / fallback + quality + action plan
                                          │
                          AnalysisSession (fingerprint-keyed snapshot)
                                          │
        ┌───────────────┬─────────────────┼──────────────────┐
        ▼               ▼                 ▼                  ▼
   Skillgap        Quiz (Gemini)    Chatbot/Interview   Notifications
   (career.py)     (quiz/utils)     (services/interview) (channels+email)
        │               │                 │                  │
        ▼               ▼                 ▼                  ▼
   roadmap/courses  results/report   grounded answers    ws push + mail
```

---

## 8. Consistency & Reliability Design

- **CV fingerprint** (SHA-256) is the single identity for CV-dependent state across analysis, quiz, skillgap and UI caches — a new upload never serves stale analysis.
- **Two-stage resume analysis** — durable save before any fallible AI step.
- **FAISS self-healing** — multi-process staleness reload, desync truncation/rebuild, lock-protected singleton.
- **Explainable scoring** — every score ships with a component ledger, strengths and deductions.
- **Graceful degradation** — no Gemini key → rule-based insights; FastAPI down → hash embeddings; Apify down → mock jobs.
- **Cache discipline** — LocMemCache + explicit invalidation on every write + `False`-caching for absent keys.

## 9. Running the Project

```bash
uv sync                    # install deps (Python 3.11)
uv run python manage.py migrate
uv run python manage.py seed_all        # optional demo data
uv run python manage.py runserver       # Django :8000
uv run uvicorn apps.fastapi_microservice.main:app --port 8001   # embeddings
uv run streamlit run main.py            # optional standalone prototype
```

- Swagger: `http://127.0.0.1:8000/swagger/` · Admin: `/django-admin/`
- `config/asgi.py` serves WebSockets (`ws/notifications/`); `ASGI_APPLICATION` is currently commented in settings (dev runs WSGI; enable for production Channels).