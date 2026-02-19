#!/usr/bin/env python3
"""
Quick test to verify browser-use extraction works with the compatibility fix.
Tests against a simple site without anti-bot protection.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv("/Users/nickborrello/Desktop/Projects/BayState/.env.local")

from browser_use import Agent, Browser
from utils.llm_wrappers import ChatOpenAI


async def test_extraction():
    """Test extraction with browser-use."""
    print("=" * 70)
    print("Browser-Use Compatibility Fix - Extraction Test")
    print("=" * 70)
    print()

    # Check API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ ERROR: OPENAI_API_KEY not set!")
        print("Please set it with: export OPENAI_API_KEY='your-key'")
        sys.exit(1)

    print(f"✓ API Key found: {api_key[:15]}...")
    print()

    # Initialize LLM with wrapper
    print("Initializing LLM with compatibility wrapper...")
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=api_key)
    print(f"✓ LLM initialized (provider={llm.provider})")
    print()

    # Initialize browser
    print("Initializing browser...")
    browser = Browser(headless=True)
    print("✓ Browser initialized")
    print()

    # Create agent
    print("Creating agent...")
    try:
        agent = Agent(
            task="Go to http://httpbin.org/html and extract the title of the page",
            llm=llm,
            browser=browser,
            max_steps=5,
        )
        print("✓ Agent created successfully!")
        print()
    except AttributeError as e:
        if "provider" in str(e):
            print(f"❌ FAILED: Provider attribute error - {e}")
            print("The compatibility fix did not work.")
            sys.exit(1)
        raise
    except Exception as e:
        print(f"❌ FAILED: {e}")
        sys.exit(1)

    # Run extraction
    print("Running extraction (this may take 30-60 seconds)...")
    print("-" * 70)
    try:
        result = await asyncio.wait_for(agent.run(), timeout=60)
        print("-" * 70)
        print()
        print("✓ EXTRACTION SUCCESSFUL!")
        print()
        print("Result:")
        print(result)
        print()

        # Save success evidence
        evidence = {
            "test": "browser-use-compatibility",
            "success": True,
            "llm_model": "gpt-4o-mini",
            "provider_attribute": llm.provider,
            "result_preview": str(result)[:500] if result else None,
        }

        import json

        evidence_path = "/Users/nickborrello/Desktop/Projects/BayState/.sisyphus/evidence/browser-use-fix-test.json"
        with open(evidence_path, "w") as f:
            json.dump(evidence, f, indent=2)
        print(f"✓ Evidence saved to: {evidence_path}")

        return True

    except asyncio.TimeoutError:
        print("-" * 70)
        print()
        print("⚠️  TIMEOUT: Extraction took too long")
        print("This may indicate the task was too complex or anti-bot detection")
        return False
    except Exception as e:
        print("-" * 70)
        print()
        print(f"❌ ERROR during extraction: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_extraction())
    sys.exit(0 if success else 1)
