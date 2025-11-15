#!/usr/bin/env python3
"""
Quick script to enable a disabled Neon endpoint using Neon API
"""
import requests
import sys

def enable_neon_endpoint(api_key, endpoint_id):
    """Enable a Neon endpoint via API"""

    # Neon API base URL
    base_url = "https://console.neon.tech/api/v2"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    print(f"🔄 Attempting to enable endpoint: {endpoint_id}")

    # Get project ID from endpoint
    # First, list all projects to find the one with this endpoint
    print("📋 Finding project...")
    projects_response = requests.get(f"{base_url}/projects", headers=headers)

    if projects_response.status_code != 200:
        print(f"❌ Failed to list projects: {projects_response.status_code}")
        print(f"Response: {projects_response.text}")
        return False

    projects = projects_response.json().get("projects", [])
    project_id = None

    for project in projects:
        # Check endpoints in this project
        project_detail = requests.get(f"{base_url}/projects/{project['id']}", headers=headers)
        if project_detail.status_code == 200:
            endpoints = project_detail.json().get("project", {}).get("endpoints", [])
            for ep in endpoints:
                if ep["id"] == endpoint_id:
                    project_id = project["id"]
                    print(f"✓ Found project: {project['name']} ({project_id})")
                    break
            if project_id:
                break

    if not project_id:
        print(f"❌ Could not find project with endpoint {endpoint_id}")
        return False

    # Enable the endpoint
    print(f"🔓 Enabling endpoint...")
    enable_url = f"{base_url}/projects/{project_id}/endpoints/{endpoint_id}/start"

    response = requests.post(enable_url, headers=headers)

    if response.status_code in [200, 201, 204]:
        print("✅ SUCCESS! Endpoint enabled and starting...")
        print("⏳ Wait 30 seconds for it to fully activate")
        return True
    else:
        print(f"❌ Failed to enable endpoint: {response.status_code}")
        print(f"Response: {response.text}")
        return False

if __name__ == "__main__":
    print("🔓 Neon Endpoint Enabler")
    print("=" * 50)

    # Get API key
    api_key = input("\n🔑 Enter your Neon API key: ").strip()

    if not api_key:
        print("❌ API key is required")
        sys.exit(1)

    # Endpoint ID from the error message
    endpoint_id = "ep-flat-paper-aem9qp8p"

    print(f"\n📍 Target endpoint: {endpoint_id}")
    print()

    success = enable_neon_endpoint(api_key, endpoint_id)

    if success:
        print("\n" + "=" * 50)
        print("✅ Done! Your Neon database should be active now.")
        print("⏳ Wait 30 seconds, then run the migration script:")
        print("   python migrate_replit_to_railway.py")
    else:
        print("\n" + "=" * 50)
        print("❌ Failed to enable endpoint.")
        print("\nAlternative: Go to https://console.neon.tech/")
        print("and manually enable the endpoint from the web UI")

    sys.exit(0 if success else 1)
