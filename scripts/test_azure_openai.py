"""Test Azure OpenAI connection and deployment."""

import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-11-20")

print("=== Azure OpenAI Configuration Test ===\n")
print(f"Endpoint: {endpoint}")
print(f"API Key: {api_key[:10]}...{api_key[-4:] if api_key else 'NOT SET'}")
print(f"Deployment: {deployment}")
print(f"API Version: {api_version}")

# Test with OpenAI library
print("\n--- Testing with OpenAI SDK ---")
try:
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint
    )

    # Simple text completion test (no image)
    print(f"Sending test request to deployment '{deployment}'...")

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "user", "content": "Say 'Hello, connection successful!' in exactly those words."}
        ],
        max_tokens=50
    )

    print(f"\nSUCCESS! Response: {response.choices[0].message.content}")
    print(f"\nModel: {response.model}")
    print(f"Usage: {response.usage}")

except Exception as e:
    print(f"\nERROR: {type(e).__name__}: {e}")

    if "404" in str(e):
        print("\n--- TROUBLESHOOTING ---")
        print("404 Resource Not Found usually means:")
        print("1. Deployment name is wrong (check Azure Portal)")
        print("2. Endpoint URL is incorrect")
        print("3. Deployment hasn't been created yet")
        print("\nCheck: Azure Portal > Your OpenAI Resource > Model Deployments")
    elif "401" in str(e) or "403" in str(e):
        print("\n--- TROUBLESHOOTING ---")
        print("Authentication error - check your API key")
    elif "connection" in str(e).lower():
        print("\n--- TROUBLESHOOTING ---")
        print("Connection error - check your endpoint URL")

print("\n--- cURL Test Command ---")
print("Run this in PowerShell to test directly:\n")
curl_cmd = f'''curl -X POST "{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}" ^
  -H "Content-Type: application/json" ^
  -H "api-key: {api_key}" ^
  -d "{{\\"messages\\": [{{\\"role\\": \\"user\\", \\"content\\": \\"Hello\\"}}], \\"max_tokens\\": 10}}"'''
print(curl_cmd)
