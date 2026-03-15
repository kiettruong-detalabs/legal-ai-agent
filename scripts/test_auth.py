#!/usr/bin/env python3
"""
Test authentication endpoints
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8080"

def test_register():
    """Test user registration"""
    print("\n=== Testing Registration ===")
    
    data = {
        "email": "test@example.com",
        "password": "SecurePass123",
        "full_name": "Test User",
        "company_name": "Test Company"
    }
    
    response = requests.post(f"{BASE_URL}/v1/auth/register", json=data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Registration successful!")
        print(f"   User ID: {result['user']['id']}")
        print(f"   Company: {result['company']['name']}")
        print(f"   API Key: {result['api_key'][:20]}...")
        print(f"   Access Token: {result['access_token'][:30]}...")
        return result
    else:
        print(f"❌ Registration failed: {response.status_code}")
        print(f"   {response.text}")
        return None

def test_login(email, password):
    """Test user login"""
    print("\n=== Testing Login ===")
    
    data = {
        "email": email,
        "password": password
    }
    
    response = requests.post(f"{BASE_URL}/v1/auth/login", json=data)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Login successful!")
        print(f"   User: {result['user']['full_name']}")
        print(f"   Role: {result['user']['role']}")
        print(f"   Company: {result['user']['company_name']}")
        print(f"   Access Token: {result['access_token'][:30]}...")
        return result
    else:
        print(f"❌ Login failed: {response.status_code}")
        print(f"   {response.text}")
        return None

def test_get_me(access_token):
    """Test /auth/me endpoint"""
    print("\n=== Testing Get Current User ===")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{BASE_URL}/v1/auth/me", headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Get user successful!")
        print(f"   Email: {result['email']}")
        print(f"   Full Name: {result['full_name']}")
        print(f"   Company Plan: {result['company']['plan']}")
        print(f"   Quota: {result['company']['used_quota']}/{result['company']['monthly_quota']}")
        return result
    else:
        print(f"❌ Get user failed: {response.status_code}")
        print(f"   {response.text}")
        return None

def test_company_info(access_token):
    """Test /company endpoint"""
    print("\n=== Testing Get Company Info ===")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{BASE_URL}/v1/company", headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Get company successful!")
        print(f"   Company: {result['name']}")
        print(f"   Slug: {result['slug']}")
        print(f"   Members: {result['stats']['members']}")
        print(f"   API Keys: {result['stats']['api_keys']}")
        return result
    else:
        print(f"❌ Get company failed: {response.status_code}")
        print(f"   {response.text}")
        return None

def test_list_keys(access_token):
    """Test /keys endpoint"""
    print("\n=== Testing List API Keys ===")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{BASE_URL}/v1/keys", headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ List keys successful!")
        print(f"   Total keys: {len(result['keys'])}")
        for key in result['keys']:
            print(f"   - {key['name']} ({key['key_prefix']}...)")
        return result
    else:
        print(f"❌ List keys failed: {response.status_code}")
        print(f"   {response.text}")
        return None

if __name__ == "__main__":
    print("🚀 Starting Authentication Tests")
    print(f"Base URL: {BASE_URL}")
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/v1/health")
        print(f"✅ Server is running")
    except Exception as e:
        print(f"❌ Server is not running. Start it with: uvicorn src.api.main:app --reload")
        sys.exit(1)
    
    # Test registration
    reg_result = test_register()
    if not reg_result:
        print("\n⚠️ Skipping remaining tests (registration failed)")
        print("   If user already exists, try login test instead")
        sys.exit(1)
    
    access_token = reg_result["access_token"]
    email = reg_result["user"]["email"]
    
    # Test get current user
    test_get_me(access_token)
    
    # Test company info
    test_company_info(access_token)
    
    # Test list API keys
    test_list_keys(access_token)
    
    # Test login with same credentials
    test_login(email, "SecurePass123")
    
    print("\n✅ All tests completed!")
