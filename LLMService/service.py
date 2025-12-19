import sys
import json
import argparse
from core import LLMCore
from utils import perform_lean_search

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, default="llm", help="Task: 'llm' or 'search'")
    args = parser.parse_args()
    try:
        input_data = sys.stdin.read()
        if not input_data: return
        req = json.loads(input_data)
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Input JSON error: {e}"}))
        return

    if args.task == "search":
        result = perform_lean_search(req.get("query", ""))
        print(json.dumps(result))
    elif args.task == "llm":
        core = LLMCore()
        response = core.process_full_request(req)
        print(json.dumps(response))
    else:
        print(json.dumps({"success": False, "message": f"Unknown task: {args.task}"}))

if __name__ == "__main__":
    main()