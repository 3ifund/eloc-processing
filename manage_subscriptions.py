"""
Azure Graph API Subscription Manager
Manages webhook subscriptions for email notifications
"""
import requests
import msal
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, UTC

load_dotenv()

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
MAILBOX_OBJECT_ID = os.getenv("MAILBOX_OBJECT_ID")
MAILBOX_EMAIL = os.getenv("MAILBOX_EMAIL")
AZURE_WEBHOOK_URL = os.getenv("AZURE_WEBHOOK_URL")
AZURE_CLIENT_STATE = os.getenv("AZURE_CLIENT_STATE", "default-secret-state")

if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, MAILBOX_OBJECT_ID, AZURE_WEBHOOK_URL]):
    print("❌ Error: Missing required environment variables!")
    print("   Make sure your .env file contains:")
    print("   - TENANT_ID")
    print("   - CLIENT_ID")
    print("   - CLIENT_SECRET")
    print("   - MAILBOX_OBJECT_ID")
    print("   - AZURE_WEBHOOK_URL")
    exit(1)


def get_access_token():
    """Authenticate with Microsoft Graph API"""
    print("🔐 Authenticating with Microsoft Graph...")
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
    
    print("✅ Authentication successful\n")
    return result["access_token"]


def list_subscriptions(access_token):
    """List all active subscriptions"""
    print("📋 Fetching active subscriptions...")
    response = requests.get(
        "https://graph.microsoft.com/v1.0/subscriptions",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    
    if response.status_code != 200:
        print(f"❌ Failed to fetch subscriptions")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        return []
    
    subscriptions = response.json().get("value", [])
    
    print(f"\n{'='*80}")
    print(f"Active Subscriptions: {len(subscriptions)}")
    print(f"{'='*80}\n")
    
    if len(subscriptions) == 0:
        print("ℹ️  No subscriptions found")
    else:
        for i, sub in enumerate(subscriptions, 1):
            print(f"#{i}:")
            print(f"  ID:          {sub['id']}")
            print(f"  Resource:    {sub['resource']}")
            print(f"  Webhook URL: {sub['notificationUrl']}")
            print(f"  Change Type: {sub['changeType']}")
            print(f"  Expires:     {sub['expirationDateTime']}")
            
            if AZURE_WEBHOOK_URL not in sub['notificationUrl']:
                print(f"  ⚠️  WARNING: This uses an OLD webhook URL!")
            
            print("-" * 80)
    
    return subscriptions


def delete_subscription(access_token, subscription_id):
    """Delete a subscription by ID"""
    print(f"\n🗑️  Deleting subscription: {subscription_id[:20]}...")
    response = requests.delete(
        f"https://graph.microsoft.com/v1.0/subscriptions/{subscription_id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    
    if response.status_code == 204:
        print("✅ Subscription deleted successfully!")
        return True
    else:
        print(f"❌ Failed to delete subscription")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        return False


def create_subscription(access_token):
    """Create a new subscription with current webhook URL"""
    # Subscription expires in 3 days (max for mailbox notifications without enhanced permissions)
    expiration = (datetime.now(UTC) + timedelta(days=3)).isoformat() + "Z"
    
    subscription_data = {
        "changeType": "created",
        "notificationUrl": AZURE_WEBHOOK_URL,
        "resource": f"/users/{MAILBOX_OBJECT_ID}/mailFolders('Inbox')/messages",
        "expirationDateTime": expiration,
        "clientState": AZURE_CLIENT_STATE
    }
    
    print(f"\n📧 Creating new subscription...")
    print(f"   Mailbox:     {MAILBOX_EMAIL or MAILBOX_OBJECT_ID}")
    print(f"   Webhook URL: {AZURE_WEBHOOK_URL}")
    print(f"   Client State: {AZURE_CLIENT_STATE}")
    print(f"   Expires:     {expiration}")
    
    response = requests.post(
        "https://graph.microsoft.com/v1.0/subscriptions",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        },
        json=subscription_data
    )
    
    if response.status_code == 201:
        sub = response.json()
        print(f"\n✅ Subscription created successfully!")
        print(f"\n{'='*80}")
        print(f"NEW SUBSCRIPTION DETAILS:")
        print(f"{'='*80}")
        print(f"  ID:          {sub['id']}")
        print(f"  Resource:    {sub['resource']}")
        print(f"  Webhook URL: {sub['notificationUrl']}")
        print(f"  Change Type: {sub['changeType']}")
        print(f"  Expires:     {sub['expirationDateTime']}")
        print(f"{'='*80}\n")
        return True
    else:
        print(f"\n❌ Failed to create subscription")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        return False


def main():
    """Main function"""
    print("\n" + "="*80)
    print("AZURE GRAPH API SUBSCRIPTION MANAGER")
    print("="*80 + "\n")
    
    access_token = get_access_token()
    
    subscriptions = list_subscriptions(access_token)
    
    if len(subscriptions) > 0:
        print("\n" + "="*80)
        print("OPTIONS:")
        print("="*80)
        print("1. Delete all subscriptions and create new one")
        print("2. Keep existing and create new one (will have multiple)")
        print("3. Exit without changes")
        
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == "1":
            print("\n🗑️  Deleting all existing subscriptions...")
            deleted_count = 0
            for sub in subscriptions:
                if delete_subscription(access_token, sub['id']):
                    deleted_count += 1
            
            print(f"\n✅ Deleted {deleted_count} subscription(s)")
            
            if create_subscription(access_token):
                print("\n✅ Setup complete!")
                print(f"\n📬 Test by sending an email to: {MAILBOX_EMAIL or 'your mailbox'}")
                print(f"🔍 Monitor webhooks at: http://localhost:4040")
            
        elif choice == "2":
            # Create new subscription (keep existing)
            if create_subscription(access_token):
                print("\n✅ New subscription created!")
                print("⚠️  Note: You now have multiple subscriptions")
                print(f"\n📬 Test by sending an email to: {MAILBOX_EMAIL or 'your mailbox'}")
                print(f"🔍 Monitor webhooks at: http://localhost:4040")
        
        else:
            print("\n👋 Exiting without changes")
    
    else:
        # No existing subscriptions, just create one
        print("\nℹ️  No existing subscriptions found")
        create_new = input("\nCreate new subscription? (y/n): ").strip().lower()
        
        if create_new == 'y':
            if create_subscription(access_token):
                print("\n✅ Setup complete!")
                print(f"\n📬 Test by sending an email to: {MAILBOX_EMAIL or 'your mailbox'}")
                print(f"🔍 Monitor webhooks at: http://localhost:4040")
        else:
            print("\n👋 Exiting without changes")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")