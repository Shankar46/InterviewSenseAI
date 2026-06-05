import requests
import json
import time

start = time.time()
form_data = {
    'topic': 'yes',
    'mode': '10 Marks',
    'task_type': 'career',
    'assistant_type': 'career',
    'chat_id': f'test-api-{int(time.time()*1000)}',
    'history': '[]',
    'career_config': json.dumps({
        'role': 'Python Developer',
        'duration': '30',
        'hours_per_day': '2',
        'level': 'beginner',
        'dsa_track': 'yes'
    })
}

try:
    resp = requests.post('http://127.0.0.1:5000/api/edtech/generate', data=form_data, timeout=120)
    elapsed = time.time() - start
    print(f'Status: {resp.status_code}')
    print(f'Time: {elapsed:.1f}s')
    if resp.ok:
        data = resp.json()
        print(f"Text length: {len(data.get('text', ''))}")
        print(f"Has tracker: {'tracker' in data}")
        print(f"Preview: {data.get('text', '')[:100]}...")
    else:
        print(f'Error: {resp.text}')
except Exception as e:
    print(f'Exception: {e}')
