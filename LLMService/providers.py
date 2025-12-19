import os
import sys
import time
import textwrap
from openai import OpenAI
from utils import log_message

class PromptManager:
    def __init__(self, prompts_dir="prompts"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.prompts_dir = os.path.join(base_dir, prompts_dir)
        self.templates = {}
        self._load_templates()

    def _load_templates(self):
        if not os.path.exists(self.prompts_dir):
            print(f"Warning: Prompts directory {self.prompts_dir} not found", file=sys.stderr)
            return
            
        for filename in os.listdir(self.prompts_dir):
            if filename.endswith(".txt"):
                key = filename.split(".")[0]
                path = os.path.join(self.prompts_dir, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.templates[key] = f.read()
                except Exception as e:
                    print(f"Error loading {filename}: {e}", file=sys.stderr)

    def render(self, template_name, context):
        tpl = self.templates.get(template_name, "")
        if not tpl:
            return f"Error: Template '{template_name}' missing in {self.prompts_dir}."
        
        try:
            return tpl.format(**context)
        except KeyError as e:
            return f"Error rendering {template_name}: Missing placeholder {e} in data."
        except Exception as e:
            return f"Error rendering {template_name}: {e}"

class CustomOpenAIProvider:
    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model_name = os.getenv("LLM_MODEL", "gpt-4o")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.api_key else None

    def generate(self, system_prompt, user_prompt):
        if not self.client: return "OpenAI client not initialized (Check LLM_API_KEY)."
        try:
            log_message(f"🧠 Sending request to LLM ({self.model_name})...")
            log_message(f"\n\nPrompt: {user_prompt}\n\n")
            start_time = time.time()

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2
            )
            duration = time.time() - start_time
            log_message(f"✅ LLM responded in {duration:.2f}s")
            return response.choices[0].message.content
        except Exception as e:
            log_message(f"❌ LLM Error: {e}")
            return f"Error calling LLM: {e}"

class MockLLMProvider:
    def __init__(self):
        default_response = textwrap.dedent("""
            <think>
            Mocking a response to test Lean side verification.
            </think>
           
            ```lean
            have h : 1=1 := rfl
            ```
            
        """)
        self.response = os.getenv("LLM_MOCK_RESPONSE", default_response)

    def generate(self, system_prompt, user_prompt):
        try:
            log_message(f"🤖 [MOCK] Returning fixed response: {self.response[:20]}...")
        except:
            pass
            
        return self.response