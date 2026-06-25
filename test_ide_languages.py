#!/usr/bin/env python3
import requests
import sys

BASE_URL = "http://127.0.0.1:5000"

def test_java():
    print("Testing Java execution...")
    code = """
public class Solution {
    public static void main(String[] args) {
        System.out.println("Hello from Java!");
    }
}
"""
    try:
        resp = requests.post(f"{BASE_URL}/api/ide/run", data={"language": "java", "code": code})
        print(f"Status: {resp.status_code}")
        print(f"Output:\n{resp.json().get('output')}\n")
    except Exception as e:
        print(f"Error: {e}\n")

def test_cpp():
    print("Testing C++ execution...")
    code = """
#include <iostream>
using namespace std;

int main() {
    cout << "Hello from C++!" << endl;
    return 0;
}
"""
    try:
        resp = requests.post(f"{BASE_URL}/api/ide/run", data={"language": "cpp", "code": code})
        print(f"Status: {resp.status_code}")
        print(f"Output:\n{resp.json().get('output')}\n")
    except Exception as e:
        print(f"Error: {e}\n")

def test_python():
    print("Testing Python execution...")
    code = "print('Hello from Python!')"
    try:
        resp = requests.post(f"{BASE_URL}/api/ide/run", data={"language": "python", "code": code})
        print(f"Status: {resp.status_code}")
        print(f"Output:\n{resp.json().get('output')}\n")
    except Exception as e:
        print(f"Error: {e}\n")

def test_javascript():
    print("Testing JavaScript execution...")
    code = "console.log('Hello from JavaScript!')"
    try:
        resp = requests.post(f"{BASE_URL}/api/ide/run", data={"language": "javascript", "code": code})
        print(f"Status: {resp.status_code}")
        print(f"Output:\n{resp.json().get('output')}\n")
    except Exception as e:
        print(f"Error: {e}\n")

if __name__ == "__main__":
    test_python()
    test_javascript()
    test_java()
    test_cpp()
