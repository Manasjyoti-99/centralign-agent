import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

class LLMClient:
    def __init__(self):
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("LLM_API_KEY is missing from environment variables.")
        self.client = Groq(api_key=api_key)
        self.model = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

    def complete(self, messages, temperature=0.2):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        return response.choices[0].message.content

if __name__ == "__main__":
    print("Initializing LLM Client...")
    llm = LLMClient()
    print("Sending test prompt to Groq...")
    reply = llm.complete([{"role": "user", "content": "Say hello"}])
    print("LLM Test Successful:", reply)
    exit(0)