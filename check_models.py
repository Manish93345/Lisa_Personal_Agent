from dotenv import load_dotenv
import os
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("\nAvailable CHAT models:\n")
for model in client.models.list():
    if "gemini" in model.name.lower() and "embed" not in model.name.lower():
        print(f"  {model.name}")
print()