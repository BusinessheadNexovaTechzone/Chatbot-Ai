#!/usr/bin/env python3
import requests
import json
import time

url = 'http://localhost:8081/api/v1/chat'

# Wait for server to be ready
time.sleep(3)

print("=" * 70)
print("COMPREHENSIVE CHAT ENDPOINT TESTS")
print("=" * 70)

# Test 1: Hello greeting
print('\n[Test 1] Greeting - "hello"')
print("-" * 70)
data = {'query': 'hello', 'session_id': 'test_1', 'stream': False, 'assistant_name': 'Assistant'}
response = requests.post(url, json=data)
result = response.json()
print(f"Status: {response.status_code}")
print(f"Intent: {result['intent']}")
print(f"Answer: {result['answer']}")
print(f"Sources: {len(result['sources'])}")

# Test 2: How are you
print('\n[Test 2] Conversational - "how are you"')
print("-" * 70)
data = {'query': 'how are you', 'session_id': 'test_2', 'stream': False, 'assistant_name': 'Assistant'}
response = requests.post(url, json=data)
result = response.json()
print(f"Status: {response.status_code}")
print(f"Intent: {result['intent']}")
print(f"Answer: {result['answer']}")

# Test 3: Domain query - Company CEO
print('\n[Test 3] Domain Query - "who is the ceo"')
print("-" * 70)
data = {'query': 'who is the ceo', 'session_id': 'test_3', 'stream': False, 'assistant_name': 'Assistant'}
response = requests.post(url, json=data)
result = response.json()
print(f"Status: {response.status_code}")
print(f"Intent: {result['intent']}")
print(f"Answer: {result['answer'][:200]}...")
if result['sources']:
    print(f"Sources: {json.dumps(result['sources'][0], indent=2)}")
print(f"Confidence: {result['confidence']}")

# Test 4: General knowledge
print('\n[Test 4] General Knowledge - "what is machine learning"')
print("-" * 70)
data = {'query': 'what is machine learning', 'session_id': 'test_4', 'stream': False, 'assistant_name': 'Assistant'}
response = requests.post(url, json=data)
result = response.json()
print(f"Status: {response.status_code}")
print(f"Intent: {result['intent']}")
print(f"Answer: {result['answer'][:200]}...")

# Test 5: Goodbye
print('\n[Test 5] Farewell - "goodbye"')
print("-" * 70)
data = {'query': 'goodbye', 'session_id': 'test_5', 'stream': False, 'assistant_name': 'Assistant'}
response = requests.post(url, json=data)
result = response.json()
print(f"Status: {response.status_code}")
print(f"Intent: {result['intent']}")
print(f"Answer: {result['answer']}")

print("\n" + "=" * 70)
print("ALL TESTS COMPLETED")
print("=" * 70)
