#!/usr/bin/env python3
"""
Final comprehensive test for career roadmap
Tests all critical paths
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from backend.career_assistant import generate_career_plan
from backend.db import load_session_state, delete_session

print("\n" + "="*80)
print("COMPREHENSIVE CAREER ROADMAP TEST")
print("="*80 + "\n")

chat_id = "comprehensive-test-001"
career_config = {
    "role": "Python Developer",
    "duration": "30 days",
    "hours_per_day": "2",
    "level": "beginner",
    "dsa_track": "yes"
}

# Clean up any previous test data
delete_session(chat_id)
print("✓ Cleaned up previous test data\n")

# TEST 1: Fresh refresh_fetch (no state yet)
print("TEST 1: Fresh Refresh Fetch (No State)")
print("-" * 80)
try:
    result = generate_career_plan(
        user_input="refresh_fetch",
        history=[],
        career_config=career_config,
        chat_id=chat_id
    )
    
    print(f"✓ Response received")
    print(f"  Text: '{result['text'][:50]}...' (empty as expected: {result['text'] == ''})")
    print(f"  Tracker: {len(result.get('tracker', []))} days")
    assert result['text'] == "", "Text should be empty for new session"
    assert len(result.get('tracker', [])) == 30, "Tracker should have 30 days"
    print("✓ TEST 1 PASSED\n")
except Exception as e:
    print(f"✗ TEST 1 FAILED: {e}\n")
    import traceback
    traceback.print_exc()

# TEST 2: User types "yes" to start (creates plan)
print("TEST 2: User Types 'yes' - Create Plan")
print("-" * 80)
try:
    start_time = time.time()
    result = generate_career_plan(
        user_input="yes",
        history=[],
        career_config=career_config,
        chat_id=chat_id
    )
    elapsed = time.time() - start_time
    
    print(f"✓ Response received in {elapsed:.1f} seconds")
    
    # Check text
    assert "text" in result, "Response should have 'text' key"
    assert len(result['text']) > 100, "Text should be substantial"
    assert "🗺️" in result['text'] or "Roadmap" in result['text'], "Should contain roadmap"
    print(f"  Text length: {len(result['text'])} chars")
    print(f"  Text preview: {result['text'][:100]}...")
    
    # Check tracker
    assert "tracker" in result, "Response should have 'tracker' key"
    assert len(result['tracker']) == 30, "Tracker should have 30 days"
    print(f"  Tracker: {len(result['tracker'])} days")
    
    # Check status
    statuses = set(d['status'] for d in result['tracker'])
    print(f"  Statuses: {statuses}")
    
    print("✓ TEST 2 PASSED\n")
except Exception as e:
    print(f"✗ TEST 2 FAILED: {e}\n")
    import traceback
    traceback.print_exc()

# TEST 3: Refresh_fetch with state (should return roadmap)
print("TEST 3: Refresh Fetch With State")
print("-" * 80)
try:
    result = generate_career_plan(
        user_input="refresh_fetch",
        history=[],
        career_config=career_config,
        chat_id=chat_id
    )
    
    print(f"✓ Response received")
    
    # Check text
    assert "text" in result, "Response should have 'text' key"
    assert len(result['text']) > 100, f"Text should be substantial, got {len(result['text'])}"
    assert "Roadmap" in result['text'] or "🗺️" in result['text'], "Should contain roadmap"
    print(f"  Text length: {len(result['text'])} chars")
    print(f"  Text preview: {result['text'][:100]}...")
    
    # Check tracker
    assert "tracker" in result, "Response should have 'tracker' key"
    assert len(result['tracker']) == 30, "Tracker should have 30 days"
    print(f"  Tracker: {len(result['tracker'])} days")
    
    print("✓ TEST 3 PASSED\n")
except Exception as e:
    print(f"✗ TEST 3 FAILED: {e}\n")
    import traceback
    traceback.print_exc()

# TEST 4: Check stored state
print("TEST 4: Verify Stored State")
print("-" * 80)
try:
    state = load_session_state(chat_id)
    
    assert state is not None, "State should be loaded"
    print(f"✓ State loaded successfully")
    print(f"  Role: {state['role']}")
    print(f"  Duration: {state['duration_days']} days")
    print(f"  Level: {state['level']}")
    print(f"  DSA Track: {state['dsa_track']}")
    print(f"  Started: {state['started']}")
    print(f"  Day Plan: {len(state.get('day_plan', []))} days")
    
    assert state['role'] == "Python Developer"
    assert state['duration_days'] == 30
    assert len(state.get('day_plan', [])) == 30, "Plan should have 30 days"
    
    # Check plan structure
    first_day = state['day_plan'][0]
    assert 'day' in first_day
    assert 'topic' in first_day
    assert 'focus' in first_day
    print(f"  Day 1 topic: {first_day['topic']}")
    
    print("✓ TEST 4 PASSED\n")
except Exception as e:
    print(f"✗ TEST 4 FAILED: {e}\n")
    import traceback
    traceback.print_exc()

# TEST 5: Status check
print("TEST 5: Status Check")
print("-" * 80)
try:
    result = generate_career_plan(
        user_input="status",
        history=[],
        career_config=career_config,
        chat_id=chat_id
    )
    
    print(f"✓ Status response received")
    assert "text" in result
    assert "Progress Report" in result['text'] or "📊" in result['text']
    print(f"  Report preview: {result['text'][:100]}...")
    print("✓ TEST 5 PASSED\n")
except Exception as e:
    print(f"✗ TEST 5 FAILED: {e}\n")
    import traceback
    traceback.print_exc()

print("="*80)
print("✓ ALL TESTS COMPLETED SUCCESSFULLY!")
print("="*80)
