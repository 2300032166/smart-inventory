"""
Full async integration test for Groq -- replicates exact FastAPI call chain.
Run: python test_async_groq.py
"""
import os
import sys
import asyncio
import logging

# Show all logs
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

# Load .env first (same as main.py)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

print("ENV CHECK:")
print(f"  AI_PROVIDER  = {os.getenv('AI_PROVIDER', '(not set)')}")
print(f"  GROQ_MODEL = {os.getenv('GROQ_MODEL', '(not set)')}")
key = os.getenv("GROQ_API_KEY", "")
print(f"  GROQ_API_KEY = {key[:6]}...{key[-4:] if key else '(EMPTY)'}")
print()

# Import the exact same modules FastAPI uses
sys.path.insert(0, os.path.dirname(__file__))

from logic.groq_client import call_groq
from logic.ai_client import generate_reasoning, load_ai_config
from logic.prompt_builder import build_prompt

async def main():
    cfg = load_ai_config()
    print("AI CONFIG:")
    print(f"  ai_provider  = {cfg.get('ai_provider')}")
    print(f"  groq_model = {cfg.get('groq_model')}")
    print(f"  groq_api_key = {'SET' if cfg.get('groq_api_key') else 'empty (will use env var)'}")
    print()

    # --- Test 1: Direct call_groq ---
    print("=" * 50)
    print("TEST 1: Direct call_groq()")
    print("=" * 50)
    try:
        result = await call_groq("Say: GROQ OK", cfg)
        print(f"PASS: {result!r}")
    except Exception as e:
        print(f"FAIL: {e}")
        print()
        print("Cannot continue -- fix call_groq first.")
        return

    # --- Test 2: generate_reasoning with real product data ---
    print()
    print("=" * 50)
    print("TEST 2: generate_reasoning() per SKU")
    print("=" * 50)

    test_products = [
        {
            "sku": "GR015",
            "name": "Salt 1kg",
            "category": "Grocery",
            "current_stock": 20,
            "unit": "pack",
            "lead_time_days": 4,
        },
        {
            "sku": "GR008",
            "name": "Wheat Flour 1kg",
            "category": "Grains",
            "current_stock": 69,
            "unit": "bag",
            "lead_time_days": 5,
        },
    ]

    test_patterns = [
        {"avg_daily_sales": 11.69, "payday_spike": False, "declining_trend": False},
        {"avg_daily_sales": 11.84, "payday_spike": False, "declining_trend": False},
    ]

    test_reorders = [
        {"days_remaining": 1.7, "urgency": "urgent", "recommended_qty": 109, "confidence_score": 100},
        {"days_remaining": 5.8, "urgency": "normal",  "recommended_qty": 73,  "confidence_score": 60},
    ]

    results = []
    for p, pat, r in zip(test_products, test_patterns, test_reorders):
        prompt = build_prompt(p, pat, r)
        print(f"\nSKU {p['sku']} ({p['name']}):")
        print(f"  Prompt length: {len(prompt)} chars")
        try:
            reasoning = await generate_reasoning(prompt)
            short = reasoning[:120].encode("ascii", errors="replace").decode("ascii")
            print(f"  Result: {short}...")
            results.append(reasoning)
        except Exception as e:
            print(f"  FAIL: {e}")
            results.append(None)

    print()
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    successes = [r for r in results if r and r != "AI explanation generation failed"]
    failures  = [r for r in results if not r or r == "AI explanation generation failed"]
    print(f"  Passed: {len(successes)}/{len(results)}")
    print(f"  Failed: {len(failures)}/{len(results)}")

    if successes and len(set(successes)) == len(successes):
        print("  Uniqueness: PASS -- all explanations are different")
    elif len(successes) > 1:
        print("  Uniqueness: WARNING -- some explanations may be identical")

if __name__ == "__main__":
    asyncio.run(main())
