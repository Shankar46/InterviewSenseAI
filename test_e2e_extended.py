#!/usr/bin/env python3
"""
E2E test with extended timeout to verify career roadmap works end-to-end
"""
import sys
import os
import json
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

print("\n" + "="*80)
print("END-TO-END CAREER ROADMAP TEST WITH EXTENDED TIMEOUT")
print("="*80 + "\n")

BASE_URL = "http://127.0.0.1:5000"
EXTENDED_TIMEOUT = 90  # Match frontend timeout

# Test with new chat ID
chat_id = f"e2e-extended-{int(time.time())}"
career_config = {
    "role": "Python Developer",
    "duration": "30 days",
    "hours_per_day": "2",
    "level": "beginner",
    "dsa_track": "yes"
}

print(f"Using chat_id: {chat_id}\n")

# TEST 1: Health check
print("TEST 1: Health Check")
print("-" * 80)
try:
    resp = requests.get(f"{BASE_URL}/api/health", timeout=10)
    print(f"✓ Server is running\n")
except Exception as e:
    print(f"✗ Server error: {e}\n")
    sys.exit(1)

# TEST 2: Refresh fetch (new session)
print("TEST 2: Refresh Fetch (New Session)")
print("-" * 80)
try:
    data = {
        "topic": "refresh_fetch",
        "mode": "10 Marks",
        "task_type": "career",
        "assistant_type": "career",
        "chat_id": chat_id,
        "history": "[]",
        "career_config": json.dumps(career_config)
    }
    
    resp = requests.post(f"{BASE_URL}/api/edtech/generate", data=data, timeout=20)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Refresh fetch successful")
        print(f"  Text: empty (as expected: {result['text'] == ''})")
        print(f"  Tracker: {len(result.get('tracker', []))} days\n")
    else:
        print(f"✗ Failed: {resp.status_code}\n")
except Exception as e:
    print(f"✗ Error: {e}\n")

# TEST 3: Start career (generate plan) - EXTENDED TIMEOUT
print("TEST 3: Start Career - Generate Plan")
print("-" * 80)
try:
    data = {
        "topic": "yes",
        "mode": "10 Marks",
        "task_type": "career",
        "assistant_type": "career",
        "chat_id": chat_id,
        "history": "[]",
        "career_config": json.dumps(career_config)
    }
    
    print(f"Sending request (timeout: {EXTENDED_TIMEOUT}s)...")
    start = time.time()
    resp = requests.post(f"{BASE_URL}/api/edtech/generate", data=data, timeout=EXTENDED_TIMEOUT)
    elapsed = time.time() - start
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Plan generated successfully in {elapsed:.1f}s")
        
        if "text" in result:
            print(f"  Text: {len(result['text'])} chars")
            has_roadmap = "Roadmap" in result['text'] or "🗺️" in result['text']
            print(f"  Contains roadmap: {has_roadmap}")
            if has_roadmap:
                print(f"  Preview: {result['text'][:100]}...")
        else:
            print(f"  ✗ No text in response!")
        
        if "tracker" in result:
            print(f"  Tracker: {len(result['tracker'])} days")
            print(f"  Statuses: {set(d['status'] for d in result['tracker'])}\n")
        else:
            print(f"  ✗ No tracker in response!\n")
    else:
        print(f"✗ Failed with status: {resp.status_code}")
        print(f"  Response: {resp.text}\n")
        
except requests.exceptions.Timeout as e:
    print(f"✗ Request timed out: {e}\n")
except Exception as e:
    print(f"✗ Error: {e}\n")

# TEST 4: Refresh fetch again (should have state now)
print("TEST 4: Refresh Fetch (With State)")
print("-" * 80)
try:
    data = {
        "topic": "refresh_fetch",
        "mode": "10 Marks",
        "task_type": "career",
        "assistant_type": "career",
        "chat_id": chat_id,
        "history": "[]",
        "career_config": json.dumps(career_config)
    }
    
    resp = requests.post(f"{BASE_URL}/api/edtech/generate", data=data, timeout=20)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Refresh fetch successful")
        
        if result['text']:
            print(f"  Text: {len(result['text'])} chars")
            has_roadmap = "Roadmap" in result['text'] or "🗺️" in result['text']
            print(f"  Contains roadmap: {has_roadmap}")
        else:
            print(f"  Text is empty (unexpected)")
        
        print(f"  Tracker: {len(result.get('tracker', []))} days\n")
    else:
        print(f"✗ Failed: {resp.status_code}\n")
except Exception as e:
    print(f"✗ Error: {e}\n")

print("="*80)
print("✓ E2E TEST COMPLETED")
print("="*80)
