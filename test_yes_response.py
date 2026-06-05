#!/usr/bin/env python3
"""Test what happens when user types 'yes' in career mode"""

import requests
import json
import time

BASE_URL = "http://localhost:5000"

def test_yes_response():
    """Test typing 'yes' which should trigger plan generation"""
    
    chat_id = f"test-yes-{int(time.time())}"
    
    print("=" * 80)
    print("TEST: Simulate User Typing 'yes'")
    print("=" * 80)
    
    # Step 1: Create a career session
    print("\n1. Creating career session...")
    form_data = {
        "topic": "yes",
        "mode": "10 Marks",
        "task_type": "career",
        "assistant_type": "career",
        "chat_id": chat_id,
        "history": json.dumps([]),
        "career_config": json.dumps({
            "role": "Python Developer",
            "duration": "30 days",
            "hours_per_day": "2",
            "level": "beginner",
            "dsa_track": "yes"
        })
    }
    
    try:
        print(f"   Sending request to {BASE_URL}/api/edtech/generate")
        print(f"   Chat ID: {chat_id}")
        print(f"   Topic: 'yes'")
        
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/api/edtech/generate",
            data=form_data,
            timeout=120  # 2 minutes
        )
        elapsed = time.time() - start_time
        
        print(f"\n✓ Response received in {elapsed:.1f}s")
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n   Response keys: {list(data.keys())}")
            text = data.get('text', '')
            print(f"\n   Text length: {len(text)}")
            print(f"   Text is empty: {text == ''}")
            print(f"   Text preview: {text[:150]}..." if text else "   Text: EMPTY")
            
            answer = data.get('answer', '')
            print(f"\n   Answer length: {len(answer)}")
            print(f"   Answer is empty: {answer == ''}")
            print(f"   Answer preview: {answer[:150]}..." if answer else "   Answer: EMPTY")
            
            print(f"\n   Tracker: {data.get('tracker', 'EMPTY')}")
            
            # The problem: if both text and answer are empty, nothing will display!
            if not text and not answer:
                print("\n   ⚠️ PROBLEM: Both 'text' and 'answer' are empty!")
                print("   This is why the screen shows empty after loading.")
                print("   The frontend displays neither because both fields are empty.")
        else:
            print(f"\n   ✗ Error: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            
    except requests.exceptions.Timeout:
        print(f"   ✗ Request timeout after 120 seconds")
    except Exception as e:
        print(f"   ✗ Error: {e}")

if __name__ == "__main__":
    test_yes_response()

