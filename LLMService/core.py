import os
import json
import re
import textwrap
from utils import CacheManager, log_message, extract_context_from_source, find_code, getenv
from providers import PromptManager, CustomOpenAIProvider, MockLLMProvider

class LLMCore:
    def __init__(self):
        self.cache_manager = CacheManager()
        self.prompt_manager = PromptManager()
        
        provider_name = getenv("LLM_PROVIDER", "openai").lower()
        if provider_name == "mock":
            self.provider = MockLLMProvider()
        else:
            self.provider = CustomOpenAIProvider()

    def handle_caching_report(self, req):
        goal = req.get("goalState")
        hint = req.get("hint")
        work_type = req.get("diagnosisInfo", "unknown")
        code = req.get("prevTactic", "")
        if code.replace('sorry', '').replace('{', '').replace('}', '').replace(';', '').strip():
            self.cache_manager.set(goal, hint, work_type, code)
            return {"success": True, "message": "Cached successfully", "tactic": ""}
        else:
            return {"success": False, "message": "Tactic with only trivial `sorry` is not cached", "tactic": ""}

    def check_cache_hit(self, req):
        req_type = req.get("requestType", "init_next")
        parts = req_type.split('_', 1)
        work_type_suffix = parts[1] if len(parts) > 1 else req_type
        
        cached_code = self.cache_manager.get(req.get("goalState"), req.get("hint"), work_type_suffix)
        if cached_code:
            return {
                "tactic": cached_code,
                "searchQuery": None,
                "analysis": None,
                "success": True,
                "message": "Returned from Cache"
            }
        return None

    def prepare_context(self, req):
        thm_decl, implicit_hint = extract_context_from_source(req.get("source"), req.get("pos"))
        return {
            "goal_state": req.get("goalState") or "No goal state.",
            "thm_decl": thm_decl or "Unknown Theorem.",
            "hint": req.get("hint") or implicit_hint or "None",
            "prev_tactic": req.get("prevTactic") or "None",
            "error_msg": re.sub(r"\S+\.lean:\d+:\d+:\s*", "", req.get("errorMsg") or "None"),
            "diagnosis": req.get("diagnosisInfo") or "None",
            "search_results": req.get("searchResults") or "No search results."
        }

    def receive_llm_request(self, req, context):
        req_type = req.get("requestType", "init_next")
        if "diagnose" in req_type:
            system_tpl = "system_diagnose"
        else:
            parts = req_type.split('_', 1)
            system_tpl = f"system_{parts[1]}" if len(parts) == 2 else "system_next"
        
        user_tpl = req_type
        system_prompt = self.prompt_manager.render(system_tpl, context)
        user_prompt = self.prompt_manager.render(user_tpl, context)
        raw_response = self.provider.generate(system_prompt, user_prompt)
        return raw_response

    def report_llm_response(self, req_type, raw_response):
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
            
            if raw_query != "NONE":
                raw_query = re.sub(r'\s+', ' ', raw_query.replace(",", " "))
            
            response_data["searchQuery"] = raw_query
            response_data["tactic"] = "skip"
            return response_data
        
        clean_response = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL)

        if req_type == "init_auto" or req_type == "init_auto_one":
            try:
                clean_json = find_code("json", clean_response) or clean_response.strip()
                parsed = json.loads(clean_json)
                response_data["analysis"] = json.dumps(parsed)
                response_data["message"] = "Plan Generated"
                return response_data
            except Exception as e:
                log_message(f"❌ JSON Parse Error in {req_type}: {e}")
                if req_type == "init_auto_one":
                     response_data["analysis"] = json.dumps({"action": "next", "hint": "Fallback: JSON parse error"})
                else:
                     response_data["analysis"] = json.dumps({"type": "COMPOUND", "plan": ["Fallback"]})
                return response_data


        else:
            raw_tactic = find_code("lean", clean_response) or clean_response.replace("`", "").strip()
            if "GIVEUP" in raw_tactic:
                 response_data["success"] = False
                 response_data["message"] = "AI explicitly gave up."
                 return response_data

            lines = raw_tactic.split('\n')
            while lines and not lines[0].strip(): lines.pop(0)
            while lines and not lines[-1].strip(): lines.pop()
            response_data["tactic"] = textwrap.dedent("\n".join(lines))
            return response_data

    def process_full_request(self, req):
        req_type = req.get("requestType", "init_next")
        
        if req_type == "report_success":
            return self.handle_caching_report(req)
        
        if req_type.startswith("init_"):
            cache_result = self.check_cache_hit(req)
            if cache_result: return cache_result

        context = self.prepare_context(req)
        raw_response = self.receive_llm_request(req, context)
        final_result = self.report_llm_response(req_type, raw_response)
        
        return final_result