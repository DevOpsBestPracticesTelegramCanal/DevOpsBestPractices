#!/usr/bin/env python
"""
Test Ollama response to check newline handling
"""
import requests
import json

OLLAMA_URL = "http://localhost:11434"
MODEL = "codegen"  # or "qwen2.5-coder:3b"

def test_ollama_response():
    print("Testing Ollama response for newlines...")
    print("=" * 60)

    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": "Write a simple Python hello world function with 3 lines",
            "stream": False,
            "options": {
                "num_predict": 100
            }
        },
        timeout=60
    )

    if response.status_code != 200:
        print(f"Error: HTTP {response.status_code}")
        return

    data = response.json()
    text = data.get("response", "")

    print(f"Raw JSON response:")
    print(json.dumps(data, indent=2)[:1000])
    print()
    print("=" * 60)
    print(f"Response text (repr):")
    print(repr(text))
    print()
    print("=" * 60)
    print(f"Response text (print):")
    print(text)
    print()
    print("=" * 60)
    print(f"Stats:")
    print(f"  Length: {len(text)}")
    print(f"  Real newlines (chr(10)): {text.count(chr(10))}")
    print(f"  Escaped \\n in text: {text.count(chr(92) + 'n')}")  # literal \n
    print(f"  Has real newlines: {chr(10) in text}")
    print(f"  Has literal backslash-n: {(chr(92) + 'n') in text}")

if __name__ == "__main__":
    test_ollama_response()
