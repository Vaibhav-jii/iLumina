import os
from google_auth_oauthlib.flow import InstalledAppFlow

# The scopes required for Google Sheets and Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def authenticate_google():
    print("Starting Google OAuth Flow...")
    
    if not os.path.exists("client_secret.json"):
        print("ERROR: client_secret.json not found in this folder!")
        return

    # This will open a browser window for you to log in
    flow = InstalledAppFlow.from_client_secrets_file(
        "client_secret.json", 
        SCOPES
    )
    
    # Capture the credentials after successful login
    creds = flow.run_local_server(port=0)
    
    # Save the token for future use
    with open("token.json", "w") as token_file:
        token_file.write(creds.to_json())
        
    print("✅ SUCCESS! You are logged in.")
    print("A 'token.json' file has been generated. Your MCP server can now use this to access your Drive automatically!")

if __name__ == "__main__":
    authenticate_google()
