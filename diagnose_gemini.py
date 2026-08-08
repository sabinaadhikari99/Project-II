"""
Standalone Gemini diagnostic - run with:

    python manage.py shell < diagnose_gemini.py

or paste its contents into `python manage.py shell` directly.

This bypasses ALL quiz-specific code (utils.py, views.py, caching,
validation) and talks to Gemini directly, so whatever it prints is the
real, unfiltered cause.
"""
import traceback

from django.conf import settings

print("=" * 60)
print("STEP 1: Is GEMINI_API_KEY configured at all?")
print("=" * 60)
key = getattr(settings, "GEMINI_API_KEY", None)
if not key:
    print("FAIL: settings.GEMINI_API_KEY is empty or missing.")
    print("      -> Set GEMINI_API_KEY in your .env / settings and restart the server.")
else:
    print(f"OK: key is set, length={len(key)}, starts with '{key[:4]}...'")

print()
print("=" * 60)
print("STEP 2: Is the google-generativeai package importable/usable?")
print("=" * 60)
try:
    import google.generativeai as genai
    print(f"OK: imported google.generativeai (version: {getattr(genai, '__version__', 'unknown')})")
except Exception as e:
    print("FAIL: could not import google.generativeai")
    traceback.print_exc()
    raise SystemExit(1)

print()
print("=" * 60)
print("STEP 3: Raw call to Gemini (gemini-2.5-flash)")
print("=" * 60)
try:
    genai.configure(api_key=key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content("Say hello in exactly one word.")
    print("SUCCESS!")
    print("Response text:", repr(response.text))
except Exception as e:
    print(f"FAILED: {type(e).__module__}.{type(e).__name__}")
    print(f"Message: {e}")
    print()
    print("Full traceback:")
    traceback.print_exc()

print()
print("=" * 60)
print("STEP 4: Package version check")
print("=" * 60)
try:
    import importlib.metadata as m
    print("google-generativeai version:", m.version("google-generativeai"))
except Exception as e:
    print("Could not determine version:", e)