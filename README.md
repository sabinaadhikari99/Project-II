# SkillSync AI

AI-powered recruitment platform using Django 4.2, DRF, SimpleJWT, SQLite, FastAPI, Sentence-BERT, FAISS, Bootstrap 5, and vanilla JavaScript.

## Setup

```powershell
uv sync
python manage.py makemigrations
python manage.py migrate
python manage.py load_mock_jobs
python manage.py runserver
```

Run the embedding microservice in a second terminal:

```powershell
uvicorn apps.fastapi_microservice.main:app --host 127.0.0.1 --port 8001
```

If the microservice or heavy ML dependencies are unavailable, Django falls back to deterministic local embeddings so development can continue.

## Standalone Resume Recommender

The Streamlit resume recommender lives in `main.py`, and the same resume-analysis workflow is integrated into the Django web app at `/ai-match/`.

Add your API keys to `.env`:

```powershell
GEMINI_API_KEY=your_gemini_key
APIFY_API_TOKEN=your_apify_token
```

Run it with:

```powershell
streamlit run main.py
```

For the production-style Django experience, run the Django app and open the AI Match page from the job seeker navbar.
