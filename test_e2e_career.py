#!/usr/bin/env python3
"""
Complete end-to-end career roadmap test
"""
import sys
import os
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

print("\n" + "="*70)
print("END-TO-END CAREER ROADMAP TEST")
print("="*70 + "\n")

BASE_URL = "http://127.0.0.1:5000"

# Test 1: Health check
print("TEST 1: Health Check")
print("-" * 70)
try:
    resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
    print(f"✓ Server is running (status: {resp.status_code})")
    print(f"  Response: {resp.json()}\n")
except Exception as e:
    print(f"✗ Server error: {e}\n")
    sys.exit(1)

# Test 2: Initial career request (should create plan)
print("TEST 2: Initial Career Request")
print("-" * 70)

chat_id = "e2e-test-001"
career_config = {
    "role": "Python Developer",
    "duration": "30 days",
    "hours_per_day": "2",
    "level": "beginner",
    "dsa_track": "yes"
}

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
    
    resp = requests.post(f"{BASE_URL}/api/edtech/generate", data=data, timeout=30)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Request successful (status: {resp.status_code})")
        
        # Check response structure
        if "text" in result:
            print(f"✓ Text field present ({len(result['text'])} chars)")
            # Show first 200 chars
            preview = result['text'][:200].replace('\n', ' ')
            print(f"  Preview: {preview}...")
        else:
            print(f"✗ Text field missing!")
            print(f"  Response: {result}")
        
        if "tracker" in result:
            print(f"✓ Tracker field present ({len(result['tracker'])} days)")
            print(f"  Statuses: {set(d['status'] for d in result['tracker'])}")
        else:
            print(f"✗ Tracker field missing!")
        
        print()
    else:
        print(f"✗ Request failed with status {resp.status_code}")
        print(f"  Response: {resp.text}\n")
        
except Exception as e:
    print(f"✗ Error: {e}\n")
    import traceback
    traceback.print_exc()

# Test 3: Check notifications
print("TEST 3: Get Notifications")
print("-" * 70)

try:
    resp = requests.get(f"{BASE_URL}/api/notifications?chat_id={chat_id}", timeout=5)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Notifications retrieved")
        print(f"  Count: {result.get('count', 0)}")
        if result.get('notifications'):
            for notif in result['notifications'][:2]:
                print(f"  - {notif.get('title')}: {notif.get('body')[:50]}")
    else:
        print(f"✗ Failed with status {resp.status_code}")
    
    print()
except Exception as e:
    print(f"✗ Error: {e}\n")

# Test 4: Refresh fetch
print("TEST 4: Refresh Fetch (Silent Progress)")
print("-" * 70)

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
    
    resp = requests.post(f"{BASE_URL}/api/edtech/generate", data=data, timeout=30)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Refresh successful")
        print(f"  Text length: {len(result.get('text', ''))} chars")
        print(f"  Tracker: {len(result.get('tracker', []))} days")
        
        if "🗺️" in result.get('text', '') or "Career Roadmap" in result.get('text', ''):
            print(f"✓ Roadmap content is present!")
        else:
            print(f"⚠ Roadmap title not found in text")
    else:
        print(f"✗ Failed with status {resp.status_code}")
    
    print()
except Exception as e:
    print(f"✗ Error: {e}\n")

# Test 5: Start day
print("TEST 5: Start Day")
print("-" * 70)

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
    
    resp = requests.post(f"{BASE_URL}/api/edtech/generate", data=data, timeout=30)
    
    if resp.status_code == 200:
        result = resp.json()
        print(f"✓ Start day successful")
        
        if "Day 1" in result.get('text', ''):
            print(f"✓ Day 1 content found!")
        else:
            print(f"⚠ Day 1 not clearly shown")
            print(f"  Text preview: {result['text'][:150]}")
    else:
        print(f"✗ Failed with status {resp.status_code}")
    
    print()
except Exception as e:
    print(f"✗ Error: {e}\n")

print("="*70)
print("✓ ALL TESTS COMPLETED")
print("="*70)
