import sys
import json
import os
import re
import textwrap
import argparse
import time
from urllib.parse import urlencode
from datetime import datetime 

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

LOG_FILE = "llm_agent.log"

def log_message(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except Exception:
        pass

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

# 注: 该服务不可用
def perform_lean_search(query: str):
    if not requests or not BeautifulSoup:
        return {
            "success": False,
            "results": "",
            "message": "Required libraries not installed. Please run 'pip install requests beautifulsoup4'."
        }

    base_url = "https://leansearch.net/"
    params = {"q": query}
    search_url = base_url + "?" + urlencode(params)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.4472.124 Safari/537.36"
    }

    max_retries = 5
    delay = 1

    for attempt in range(max_retries):
        try:
            response = requests.get(search_url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")
            cards = soup.find_all("article", class_="card")

            if not cards:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                else:
                    return {
                        "success": True,
                        "results": f"Search for \"{query}\" failed after {max_retries} attempts, likely due to rate limiting. The server returned an empty result page.",
                        "message": "Rate limit suspected."
                    }
            
            formatted_results = []
            for card in cards[:20]:
                name_tag = card.find("span", class_="formal-name")
                type_tag = card.find("pre", class_="formal-statement")
                if name_tag and type_tag:
                    name = name_tag.get_text(strip=True)
                    type_info = type_tag.get_text(strip=True)
                    if name and type_info:
                        formatted_results.append(f"{name} : {type_info}")

            if not formatted_results:
                return {
                    "success": True,
                    "results": f"Could not parse any valid theorems from leansearch.net for query: \"{query}\"",
                    "message": "Parsing failed on received HTML."
                }
            return {
                "success": True,
                "results": "\n".join(formatted_results),
                "message": "OK"
            }

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                return {
                    "success": False,
                    "results": "",
                    "message": f"HTTP request failed after {max_retries} retries: {e}"
                }
        except Exception as e:
            return {
                "success": False,
                "results": "",
                "message": f"An unexpected error occurred during web scraping: {e}"
            }
            
    return {
        "success": False,
        "results": "",
        "message": "Search failed unexpectedly after all retries."
    }

def handle_llm_request(req):
    context = {
        "goal_state": req.get("goalState") or "No goal state.",
        "thm_decl": req.get("fullThm") or "Theorem not available.",
        "hint": req.get("hint") or "None",
        "prev_tactic": req.get("prevTactic") or "None",
        "error_msg": re.sub(r"\S+\.lean:\d+:\d+:\s*", "", req.get("errorMsg") or "None"),
        "diagnosis": req.get("diagnosisInfo") or "None",
        "search_results": req.get("searchResults") or "No search results."
    }

    req_type = req.get("requestType", "init_next")

    log_message("-" * 40)
    log_message(f"📥 New Request: {req_type}")
    
    if "diagnose" in req_type:
        system_tpl_name = "system_diagnose"
    else:
        parts = req_type.split('_', 1)
        if len(parts) == 2:
            suffix = parts[1]
            system_tpl_name = f"system_{suffix}"
        else:
            raise ValueError("Unknown prompt format")
    user_tpl_name = req_type
    pm = PromptManager()
    provider_name = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider_name == "openai":
        provider = CustomOpenAIProvider()
    elif provider_name == "mock":
        provider = MockLLMProvider()
    else:
        print(json.dumps({"success": False, "message": f"Unknown LLM_PROVIDER: {provider_name}"}))
        return

    system_prompt = pm.render(system_tpl_name, context)
    user_prompt = pm.render(user_tpl_name, context)

    raw_response = provider.generate(system_prompt, user_prompt)

    response_data = {
        "tactic": "",
        "searchQuery": None,
        "analysis": None,
        "success": True,
        "message": "OK"
    }

    if "diagnose" in req_type:
        analysis_match = re.search(r'ANALYSIS:\s*(.+?)(?=SEARCH:|$)', raw_response, re.DOTALL | re.IGNORECASE)
        search_match = re.search(r'SEARCH:\s*(.+)', raw_response, re.IGNORECASE)
        
        response_data["analysis"] = analysis_match.group(1).strip() if analysis_match else raw_response
        raw_query = search_match.group(1).strip() if search_match else "NONE"

        log_message(f"🩺 Diagnosis: {response_data['analysis']}")
        if raw_query != "NONE":
            raw_query = raw_query.replace(",", " ")
            raw_query = re.sub(r'\s+', ' ', raw_query)
            log_message(f"🔑 Suggest Search: {raw_query}")
            
        response_data["searchQuery"] = raw_query
        response_data["tactic"] = "skip" 
    else:
        clean_response = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL)
        code_match = re.search(r'```(?:lean)?(.*?)```', clean_response, re.DOTALL)
        if code_match:
            raw_tactic_block = code_match.group(1)
            lines = raw_tactic_block.split('\n')
            while lines and not lines[0].strip(): lines.pop(0)
            while lines and not lines[-1].strip(): lines.pop()
            code_without_blank_lines = "\n".join(lines)
            if code_without_blank_lines:
                final_tactic_code = textwrap.dedent(code_without_blank_lines)
            else:
                final_tactic_code = ""
            # 特殊处理, 此时已经完全对齐. TypeGen 不会关闭目标
            if "type" in req_type and final_tactic_code:
                pass
                final_tactic_code = final_tactic_code + "\nsorry"
            response_data["tactic"] = final_tactic_code
        else:
            response_data["tactic"] = clean_response.replace("`", "")

        if response_data["tactic"]:
            log_message(f"💡 Generated Tactic:\n{textwrap.indent(response_data['tactic'], '   ')}")
        else:
             log_message("⚠️ No tactic generated.")

    print(json.dumps(response_data))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, default="llm", help="Task to perform: 'llm' or 'search'")
    args = parser.parse_args()

    try:
        input_data = sys.stdin.read()
        if not input_data: return
        req = json.loads(input_data)
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Input JSON error: {e}"}))
        return

    if args.task == "search":
        query = req.get("query", "")
        result = perform_lean_search(query)
        print(json.dumps(result))
    elif args.task == "llm":
        handle_llm_request(req)
    else:
        print(json.dumps({"success": False, "message": f"Unknown task: {args.task}"}))

if __name__ == "__main__":
    main()
