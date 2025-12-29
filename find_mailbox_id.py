import requests
import msal
from datetime import datetime, timedelta

# ===== YOUR CREDENTIALS =====
TENANT_ID = "2137618d-a04d-440d-8723-344afe326d1d"
CLIENT_ID = "787bdf78-8c1a-4c91-b91e-811953cfac34"
CLIENT_SECRET = "ImL8Q~mz0NVXxDbI5iQ0PHnBnKIMa2rQrYLZIaBw"

# ===== WEBHOOK URL =====
WEBHOOK_URL = "https://unimposed-bleakish-magdalena.ngrok-free.dev/webhook/email"

# ===== MAILBOX OBJECT ID =====
MAILBOX_OBJECT_ID = "43f0c5ce-3487-4b32-b2a3-a4ecaa308358"
MAILBOX_EMAIL = "eloc@3ifund.com"

CLIENT_STATE = "SecretToken12345"

# ========================================

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
    print(f"\n❌ Authentication failed:")
    print(f"   Error: {result.get('error')}")
    print(f"   Description: {result.get('error_description')}")
    exit(1)

access_token = result["access_token"]
print("✅ Authentication successful")

# Create subscription
print(f"\n📝 Creating webhook subscription...")
print(f"   Mailbox: {MAILBOX_EMAIL}")
print(f"   Object ID: {MAILBOX_OBJECT_ID}")
print(f"   Webhook URL: {WEBHOOK_URL}")

subscription_data = {
    "changeType": "created",
    "notificationUrl": WEBHOOK_URL,
    "resource": f"users/{MAILBOX_OBJECT_ID}/messages",
    "expirationDateTime": (datetime.utcnow() + timedelta(hours=72)).isoformat() + "Z",
    "clientState": CLIENT_STATE
}

headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

response = requests.post(
    "https://graph.microsoft.com/v1.0/subscriptions",
    json=subscription_data,
    headers=headers
)

print(f"\n📡 Response Status: {response.status_code}")

if response.status_code == 201:
    subscription = response.json()
    
    print("\n" + "=" * 70)
    print("🎉 SUCCESS! Webhook subscription created!")
    print("=" * 70)
    print(f"Subscription ID: {subscription['id']}")
    print(f"Expires: {subscription['expirationDateTime']}")
    print(f"Resource: {subscription['resource']}")
    print(f"Notification URL: {subscription['notificationUrl']}")
    
    # Save subscription ID to file
    with open("subscription_id.txt", "w") as f:
        f.write(subscription['id'])
    
    print(f"\n💾 Subscription ID saved to: subscription_id.txt")
    
    print(f"\n" + "=" * 70)
    print(f"✉️  TEST IT NOW:")
    print(f"=" * 70)
    print(f"1. Send email with PDF attachment to: {MAILBOX_EMAIL}")
    print(f"2. Watch Terminal #1 (FastAPI) for webhook notification")
    print(f"3. Check C:\\temp\\attachments\\ for downloaded files")
    print(f"\n👀 You should see:")
    print(f"   - Email subject, sender, attachments in FastAPI logs")
    print(f"   - 'Downloaded: filename.pdf' message")
    print(f"   - Files saved to C:\\temp\\attachments\\")
    print("=" * 70)
    
elif response.status_code == 400:
    print(f"\n❌ Subscription creation failed - Bad Request")
    print(f"\nResponse:")
    print(response.text)
    print(f"\n💡 Common issues:")
    print(f"   - Is FastAPI running? (Terminal #1)")
    print(f"   - Is ngrok running? (Terminal #2)")
    print(f"   - Is the webhook URL accessible?")
    print(f"\n🔧 Try:")
    print(f"   Visit: {WEBHOOK_URL.replace('/webhook/email', '/health')}")
    print(f"   Should return: {{\"status\":\"healthy\"}}")
    
elif response.status_code == 403:
    print(f"\n❌ Subscription creation failed - Forbidden")
    print(f"\nResponse:")
    print(response.text)
    print(f"\n💡 This means:")
    print(f"   - Admin consent may not be active")
    print(f"   - Verify permissions were granted in Azure Portal")
    
elif response.status_code == 404:
    print(f"\n❌ Subscription creation failed - Not Found")
    print(f"\nResponse:")
    print(response.text)
    print(f"\n💡 This means:")
    print(f"   - The mailbox Object ID might be incorrect")
    print(f"   - Current Object ID: {MAILBOX_OBJECT_ID}")
    print(f"   - Verify this is correct in Azure Portal")
    
else:
    print(f"\n❌ Subscription creation failed")
    print(f"   Status Code: {response.status_code}")
    print(f"\nFull Response:")
    print(response.text)