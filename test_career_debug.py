#!/usr/bin/env python3
"""
Debug script for career roadmap endpoint
"""
import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# Test 1: Import modules
print("=" * 60)
print("TEST 1: Importing modules...")
print("=" * 60)

try:
    from backend.career_assistant import generate_career_plan
    print("✓ Successfully imported generate_career_plan")
except Exception as e:
    print(f"✗ Failed to import: {e}")
    sys.exit(1)

try:
    from backend.db import load_session_state, save_session_state
    print("✓ Successfully imported DB functions")
except Exception as e:
    print(f"✗ Failed to import DB functions: {e}")
    sys.exit(1)

# Test 2: Test generate_career_plan with "yes" input (start)
print("\n" + "=" * 60)
print("TEST 2: Generate Career Plan - Initial Setup")
print("=" * 60)

chat_id = "debug-test-001"
career_config = {
    "role": "Python Developer",
    "duration": "30 days",
    "hours_per_day": "2",
    "level": "beginner",
    "dsa_track": "yes"
}

try:
    result = generate_career_plan(
        user_input="yes",
        history=[],
        career_config=career_config,
        chat_id=chat_id
    )
    
    print(f"\nResult type: {type(result)}")
    print(f"Result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
    
    if "text" in result:
        print(f"\n✓ Text field present")
        print(f"Text length: {len(result['text'])} characters")
        print(f"Text preview:\n{result['text'][:300]}...")
    else:
        print("✗ Text field missing!")
    
    if "tracker" in result:
        print(f"\n✓ Tracker field present")
        print(f"Tracker: {json.dumps(result['tracker'][:3], indent=2)}...")
    else:
        print("✗ Tracker field missing!")
        
    # Print full result
    print(f"\n\nFull Response:\n{json.dumps(result, indent=2)[:1000]}")
    
except Exception as e:
    print(f"✗ Error calling generate_career_plan: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Check stored state
print("\n" + "=" * 60)
print("TEST 3: Check Stored Session State")
print("=" * 60)

try:
    state = load_session_state(chat_id)
    if state:
        print(f"✓ Session state loaded")
        print(f"  Role: {state.get('role')}")
        print(f"  Duration: {state.get('duration_days')} days")
        print(f"  Started: {state.get('started')}")
        print(f"  Day Plan exists: {len(state.get('day_plan', [])) > 0}")
        if state.get('day_plan'):
            print(f"  Plan preview: {json.dumps(state['day_plan'][:2], indent=2)}")
    else:
        print("✗ No session state found")
except Exception as e:
    print(f"✗ Error loading session state: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Test refresh_fetch
print("\n" + "=" * 60)
print("TEST 4: Test Refresh Fetch (silent progress)")
print("=" * 60)

try:
    result = generate_career_plan(
        user_input="refresh_fetch",
        history=[],
        career_config=career_config,
        chat_id=chat_id
    )
    
    print(f"\n✓ Refresh fetch successful")
    print(f"Text length: {len(result.get('text', ''))} characters")
    print(f"Tracker length: {len(result.get('tracker', []))}")
    print(f"Text preview:\n{result['text'][:200] if 'text' in result else 'No text'}...")
    
except Exception as e:
    print(f"✗ Error in refresh_fetch: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("DEBUG TESTS COMPLETE")
print("=" * 60)
