import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io
import json
from pathlib import Path
import pyautogui
from google import genai
from google.genai import types as gtypes
from config import get_config

def test_screen_find(description, model_name):
    config = get_config()
    api_key = config.get("gemini_api_key", "")
    if not api_key:
        print("Failed to get API key from config.get_config()")
        return

    w, h = pyautogui.size()
    img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    client = genai.Client(api_key=api_key)

    print(f"\n--- Testing with {model_name} ---")
    
    # Using 2D spatial bounding box
    prompt = f'Return a 2D bounding box [ymin, xmin, ymax, xmax] for the UI element described as: "{description}". Return ONLY the box coordinates.'

    response = client.models.generate_content(
        model=model_name,
        contents=[
            gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            prompt,
        ],
    )
    print("Response:")
    print(response.text)

if __name__ == "__main__":
    desc = "Ishan Patel account"
    test_screen_find(desc, "gemini-2.5-flash")
    test_screen_find(desc, "gemini-2.5-pro")
