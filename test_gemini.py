import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("Không tìm thấy GEMINI_API_KEY trong file .env")

client = genai.Client(api_key=api_key)

interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input="Trả lời đúng một câu: Gemini API đang hoạt động."
)

print("=== GEMINI TEST ===")
print(interaction.output_text)