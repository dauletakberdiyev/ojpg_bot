#!/usr/bin/env python3
"""
Yandex Cloud IAM Token Helper

This script helps you get an IAM token for Yandex Cloud Vision API.
There are different ways to authenticate depending on your setup.
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

def get_iam_token_with_oauth(oauth_token: str) -> dict:
    """Get IAM token using OAuth token"""
    url = "https://iam.api.yandexcloud.kz/iam/v1/tokens"
    headers = {"Content-Type": "application/json"}
    data = {"yandexPassportOauthToken": oauth_token}
    
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

def get_iam_token_with_service_account(service_account_key_file: str) -> dict:
    """Get IAM token using service account key file"""
    import jwt
    import time
    
    # Read service account key
    with open(service_account_key_file, 'r') as f:
        service_account_key = json.load(f)
    
    # Create JWT
    now = int(time.time())
    payload = {
        'aud': 'https://iam.api.cloud.yandex.net/iam/v1/tokens',
        'iss': service_account_key['service_account_id'],
        'iat': now,
        'exp': now + 3600  # 1 hour
    }
    
    # Sign JWT
    encoded_token = jwt.encode(
        payload,
        service_account_key['private_key'],
        algorithm='PS256',
        headers={'kid': service_account_key['id']}
    )
    
    # Exchange JWT for IAM token
    url = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
    headers = {"Content-Type": "application/json"}
    data = {"jwt": encoded_token}
    
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

def get_iam_token_with_metadata_service() -> dict:
    """Get IAM token using metadata service (for VMs in Yandex Cloud)"""
    url = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
    headers = {"Metadata-Flavor": "Google"}
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def save_token_to_env(iam_token: str):
    """Save IAM token to .env file"""
    env_file = ".env"
    env_vars = {}
    
    # Read existing .env file
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key] = value
    
    # Update IAM token
    env_vars['YANDEX_IAM_TOKEN'] = iam_token
    
    # Write back to .env file
    with open(env_file, 'w') as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
    
    print(f"✅ IAM token saved to {env_file}")

def main():
    print("🔑 Yandex Cloud IAM Token Helper")
    print("=" * 40)
    
    # Check which method to use
    oauth_token = os.getenv('YANDEX_OAUTH_TOKEN')
    service_account_key_file = os.getenv('YANDEX_SERVICE_ACCOUNT_KEY_FILE')
    
    try:
        if oauth_token:
            print("📱 Using OAuth token method...")
            result = get_iam_token_with_oauth(oauth_token)
            
        elif service_account_key_file and os.path.exists(service_account_key_file):
            print("🔐 Using Service Account key file method...")
            result = get_iam_token_with_service_account(service_account_key_file)
            
        else:
            print("☁️ Trying metadata service method (for Yandex Cloud VMs)...")
            result = get_iam_token_with_metadata_service()
        
        # Extract token and expiration
        iam_token = result['iamToken']
        expires_at = result.get('expiresAt', 'Unknown')
        
        print(f"✅ Successfully obtained IAM token!")
        print(f"📅 Expires at: {expires_at}")
        print(f"🔑 Token: {iam_token[:20]}...{iam_token[-20:]}")
        
        # Save to .env file
        save_token_to_env(iam_token)
        
        # Show how long until expiration
        if expires_at != 'Unknown':
            try:
                expire_time = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                time_left = expire_time - datetime.now(expire_time.tzinfo)
                print(f"⏰ Token expires in: {time_left}")
                
                if time_left < timedelta(hours=1):
                    print("⚠️  Warning: Token expires soon!")
            except:
                pass
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error getting IAM token: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    main()

# Instructions for different authentication methods:
"""
METHOD 1: OAuth Token (Simplest for personal use)
1. Go to https://oauth.yandex.ru/authorize?response_type=token&client_id=1a6990aa636648e9b2ef855fa7bec2fb
2. Allow access and copy the token from URL
3. Add to .env: YANDEX_OAUTH_TOKEN=your_oauth_token_here
4. Run: python yandex_iam_helper.py

METHOD 2: Service Account Key File (Recommended for production)
1. Create service account in Yandex Cloud Console
2. Generate key file for the service account
3. Download the JSON key file
4. Add to .env: YANDEX_SERVICE_ACCOUNT_KEY_FILE=path/to/key.json
5. Install PyJWT: pip install PyJWT[crypto]
6. Run: python yandex_iam_helper.py

METHOD 3: Metadata Service (For VMs running in Yandex Cloud)
1. Create VM with service account attached
2. Run: python yandex_iam_helper.py

Note: IAM tokens expire after 12 hours, so you'll need to refresh them regularly.
For production use, implement automatic token refresh in your bot.
"""