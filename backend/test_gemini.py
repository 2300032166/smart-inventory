"""
Gemini model-finder — tries each available model until one works.
Run: python test_gemini.py
"""

import os, sys, time

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    print("[1] .env loaded")
except ImportError:
    print("[1] python-dotenv not installed -- using system env")

api_key = os.getenv("GEMINI_API_KEY", "")
if not api_key:
    print("[2] FAIL -- GEMINI_API_KEY is empty in .env")
    sys.exit(1)
print(f"[2] API key: {api_key[:6]}...{api_key[-4:]}")

try:
    import google.generativeai as genai
    print(f"[3] google-generativeai {genai.__version__} imported")
except ImportError:
    print("[3] FAIL -- run: pip install google-generativeai")
    sys.exit(1)

genai.configure(api_key=api_key)
print("[4] genai.configure() OK")

# Collect all models that support generateContent
print("[5] Fetching models that support generateContent ...")
try:
    supported = [
        m.name for m in genai.list_models()
        if "generateContent" in list(m.supported_generation_methods)
    ]
    print(f"      {len(supported)} models support generateContent")
except Exception as e:
    print(f"[5] Cannot list models: {e}")
    supported = []

# Priority order: prefer fast, stable generation models
PREFERRED = [
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash-8b",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

# Add any extras from the live list not already in PREFERRED
for m in supported:
    short = m.replace("models/", "")
    if (short not in PREFERRED
            and "flash" in short.lower()
            and "tts" not in short
            and "audio" not in short
            and "image" not in short
            and "live" not in short):
        PREFERRED.append(short)

print(f"\n[6] Testing {len(PREFERRED)} candidate models ...")
test_prompt = "In one sentence, explain why a grocery store manager should reorder milk when stock is low."
working_model = None

for candidate in PREFERRED:
    print(f"    Testing {candidate} ... ", end="", flush=True)
    try:
        model = genai.GenerativeModel(candidate)
        resp = model.generate_content(test_prompt)
        text = resp.text.strip()
        preview = text[:80].encode("ascii", errors="replace").decode("ascii")
        print(f"OK ({len(text)} chars): {preview}")
        working_model = candidate
        break
    except Exception as e:
        err = str(e)
        if "429" in err or "quota" in err.lower():
            print("QUOTA EXCEEDED (skipping)")
        elif "404" in err or "not found" in err.lower():
            print("NOT FOUND (skipping)")
        else:
            safe_err = err[:80].encode("ascii", errors="replace").decode("ascii")
            print(f"ERROR: {safe_err}")
        time.sleep(0.4)

print()
if working_model:
    print("=" * 60)
    print(f"WORKING MODEL FOUND: {working_model}")
    print()
    print("Update your backend/.env:")
    print(f"  GEMINI_MODEL={working_model}")
    print()
    print("Update backend/data/ai_config.json:")
    print(f'  "gemini_model": "{working_model}"')
    print("=" * 60)

    # Verify unique outputs per unique SKU prompt
    print("\n[7] Verifying unique outputs per SKU prompt ...")
    prompts = [
        "In 2 sentences, explain why Salt 1kg (SKU: GR015, stock: 20 packs, avg 11.69/day, lead time 4 days) needs urgent reorder.",
        "In 2 sentences, explain why Wheat Flour 1kg (SKU: GR008, stock: 69 bags, avg 11.84/day, lead time 5 days) needs reorder.",
        "In 2 sentences, explain why Sugar 1kg (SKU: GR005, stock: 50 bags, avg 11.46/day, lead time 4 days) needs reorder.",
    ]
    results = []
    m = genai.GenerativeModel(working_model)
    for i, p in enumerate(prompts, 1):
        r = m.generate_content(p).text.strip()
        results.append(r)
        preview = r[:90].encode("ascii", errors="replace").decode("ascii")
        print(f"  SKU {i}: {preview}...")
        time.sleep(0.5)

    if len(set(results)) == len(results):
        print("\n[7] PASS -- All 3 prompts returned DIFFERENT text")
    else:
        print("\n[7] WARNING -- Some responses were identical")

else:
    print("=" * 60)
    print("NO WORKING MODEL FOUND")
    print()
    print("All tested models are quota-exceeded for this API key.")
    print("Options:")
    print("  1. Wait 24 hours for daily quota to reset")
    print("  2. Create a new API key: https://aistudio.google.com/app/apikey")
    print("  3. Enable billing: https://console.cloud.google.com/billing")
    print("=" * 60)
    sys.exit(1)
