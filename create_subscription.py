import requests
import msal
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Configuration from .env
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# Validate required environment variables
if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
    print("❌ Error: Missing required environment variables!")
    print("   Make sure your .env file contains:")
    print("   - TENANT_ID")
    print("   - CLIENT_ID")
    print("   - CLIENT_SECRET")
    exit(1)

print("🔐 Authenticating with Microsoft Graph...")

# Get access token
authority = f"https://login.microsoftonline.com/{TENANT_ID}"
app = msal.ConfidentialClientApplication(
    CLIENT_ID, 
    authority=authority, 
    client_credential=CLIENT_SECRET
)

result = app.acquire_token_for_client(
    scopes=["https://graph.microsoft.com/.default"]
)

if "access_token" not in result:
    print(f"❌ Authentication failed!")
    print(f"   Error: {result.get('error_description')}")
    exit(1)

access_token = result["access_token"]
print("✅ Authentication successful\n")

# List all subscriptions
print("📋 Fetching active subscriptions...")
response = requests.get(
    "https://graph.microsoft.com/v1.0/subscriptions",
    headers={"Authorization": f"Bearer {access_token}"}
)

if response.status_code != 200:
    print(f"❌ Failed to fetch subscriptions")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
    exit(1)

subscriptions = response.json().get("value", [])

print(f"\n{'='*70}")
print(f"Active Subscriptions: {len(subscriptions)}")
print(f"{'='*70}\n")

if len(subscriptions) == 0:
    print("❌ No subscriptions found!")
    print("   You need to run: python create_subscription.py")
else:
    for i, sub in enumerate(subscriptions, 1):
        print(f"Subscription #{i}:")
        print(f"  ID: {sub['id']}")
        print(f"  Resource: {sub['resource']}")
        print(f"  Webhook URL: {sub['notificationUrl']}")
        print(f"  Change Type: {sub['changeType']}")
        print(f"  Expires: {sub['expirationDateTime']}")
        print("-" * 70)

print(f"\n✅ Done! Found {len(subscriptions)} subscription(s)")