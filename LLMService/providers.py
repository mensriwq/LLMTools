import os
import sys
import time
import textwrap
import random
from openai import OpenAI
from utils import log_message, getenv

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
        self.api_key = getenv("LLM_API_KEY")
        self.base_url = getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model_name = getenv("LLM_MODEL", "gpt-4o")
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
        self.default_template = textwrap.dedent("""
            <think>
            Mocking a response to test Lean side verification.
            Random ID: {random}
            </think>
            Test for json:
            ```json
            {
                "type": "CHAIN",
                "plan": [
                    "use some rfl 1",
                    "use some rfl 2"
                ]
            }
            ```
            Test for lean:
            ```lean
            have h{random} : 1 = 1 := rfl
            have : 2 = 2 := rfl
            ```
        """)
        self.response_template = getenv("LLM_MOCK_RESPONSE", self.default_template)

    def generate(self, system_prompt, user_prompt):
        try:
            log_message(f"🤖 User prompt: {user_prompt}...\n\n")
            rand_id = str(random.randint(10000000, 99999999))
            response = self.response_template.replace("{random}", rand_id)
            log_message(f"🤖 [MOCK] Returning fixed response: {response}...")
        except Exception as e:
            log_message(f"❌ Mock LLM Error: {e}")
            response = self.response_template
            
        return response