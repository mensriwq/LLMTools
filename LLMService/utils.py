import os
import json
import hashlib
import re
import time
import requests
from datetime import datetime
from urllib.parse import urlencode

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

LOG_FILE = "llm_agent.log"
CACHE_FILE = "llm_cache.json"

def log_message(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except Exception:
        pass

class CacheManager:
    def __init__(self):
        self.cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_FILE)
        self.cache = self._load_cache()

    def _load_cache(self):
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            log_message(f"⚠️ Failed to save cache: {e}")

    def _generate_key(self, goal, hint, work_type):
        g = (goal or "").strip()
        h = (hint or "None").strip()
        w = (work_type or "").strip()
        raw_key = f"{g}||{h}||{w}"
        return hashlib.md5(raw_key.encode('utf-8')).hexdigest()

    def get(self, goal, hint, work_type):
        key = self._generate_key(goal, hint, work_type)
        if key in self.cache:
            log_message(f"⚡ Cache Hit for [{work_type}]")
            return self.cache[key]
        return None

    def set(self, goal, hint, work_type, code):
        key = self._generate_key(goal, hint, work_type)
        if "```lean" not in code:
            code = f"```lean\n{code}\n```"
        
        self.cache[key] = code
        self._save_cache()
        log_message(f"💾 Cached success for [{work_type}]")

def classify_error(error_msg):
    msg = error_msg.lower()
    
    # 1. Missing / Hallucination
    if any(k in msg for k in [
        "unknown identifier", "unknown constant", "unknown declaration",
        "failed to synthesize", "instance problem is stuck", "hypothesis", "not found"
    ]):
        return "missing"

    # 2. Type / Syntax
    if any(k in msg for k in [
        "type mismatch", "application type mismatch", "expected type", 
        "function expected", "too many arguments", "invalid", "notation",
        "not a definitional equality"
    ]):
        return "type"

    # 3. Tactic Failure
    # "no goals", "unsolved goals"
    if any(k in msg for k in [
        "tactic", "failed", "no applicable"
    ]):
        return "failure"
    
    # 4. Resource
    if any(k in msg for k in ["heartbeats", "recursion", "timeout"]):
        return "resource"

    return "general"

def extract_context_from_source(source, pos):
    if not source or pos is None:
        return None, None

    # 提取隐式提示
    try:
        source_bytes = source.encode('utf-8')
        if pos > len(source_bytes):
            pos = len(source_bytes)
        prefix_bytes = source_bytes[:pos]
        prefix = prefix_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        prefix = source[:pos]

    lines = prefix.split('\n')
    
    implicit_hint = None
    hint_lines = []
    
    if lines:
        lines.pop()

    while lines:
        line = lines[-1].strip()
        if line.startswith("--"):
            content = line.lstrip("-").strip()
            hint_lines.append(content)
            lines.pop()
        elif line:
            break

    if hint_lines:
        implicit_hint = "\n".join(reversed(hint_lines))

    # 提取定理声明
    keywords = ["theorem", "lemma", "def", "instance", "example", "structure", "class"]
    decl_start_index = -1
    found_keyword = ""

    for keyword in keywords:
        pattern = re.compile(r'\b' + keyword + r'\b')
        for match in pattern.finditer(prefix):
            match_idx = match.start()
            
            line_start = prefix.rfind('\n', 0, match_idx) + 1
            line_before_kw = prefix[line_start:match_idx]
            if "--" in line_before_kw:
                continue
            if match_idx > decl_start_index:
                decl_start_index = match_idx
                found_keyword = keyword
    
    theorem_decl = "Theorem context not found."

    if decl_start_index != -1:
        raw_decl = prefix[decl_start_index:]
        cut_idx = len(raw_decl)
        balance = 0
        in_string = False
        in_char = False
        found_end = False
        
        for i, char in enumerate(raw_decl):
            if in_string:
                if char == '"' and raw_decl[i-1] != '\\': in_string = False
                continue
            if in_char:
                if char == "'" and raw_decl[i-1] != '\\': in_char = False
                continue
                
            if char == '"': 
                in_string = True
                continue
            if char == "'": 
                in_char = True
                continue

            if char in '({[':
                balance += 1
            elif char in ')}]':
                balance -= 1
            if balance == 0:
                if raw_decl[i:].startswith(":="):
                    cut_idx = i
                    found_end = True
                    break
                if (raw_decl[i:].startswith(" by ") or 
                    raw_decl[i:].startswith("\nby ") or
                    (raw_decl[i:].startswith("by ") and (i==0 or raw_decl[i-1].isspace()))):
                    cut_idx = i
                    found_end = True
                    break
                if (raw_decl[i:].startswith(" where ") or 
                    raw_decl[i:].startswith("\nwhere ")):
                    cut_idx = i
                    found_end = True
                    break

        theorem_decl = raw_decl[:cut_idx].strip()
        if len(theorem_decl) < len(found_keyword) + 2:
            theorem_decl = raw_decl

    return theorem_decl, implicit_hint

def perform_lean_search(query: str):
    raise NotImplementedError("Won't work.")
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