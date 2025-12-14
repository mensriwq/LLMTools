import Lean
import LLMTools.Core 

open Lean Meta Elab Tactic

inductive SearchProvider where
  | localEnv
  | leanSearchNet
  deriving Inhabited, BEq

def getSearchProviderFromEnv : IO SearchProvider := do
  let providerStr ← IO.getEnv "LEAN_LLM_SEARCH_PROVIDER"
  match providerStr with
  | some "leansearch" => pure .leanSearchNet
  | _                 => pure .localEnv

def findTheoremsLocal (keywords : String) : TacticM String := do
  if keywords == "NONE" || keywords == "" then return "No search performed."

  let env ← getEnv
  let keywordList := (keywords.splitOn " " |>.filter (· != "") |>.map String.toLower).eraseDups

  let matchesArray := env.constants.fold (init := #[]) fun acc name info =>
    if info.isUnsafe || Lean.Name.isInternal name then acc else
      let nStr := name.toString.toLower
      let score := keywordList.foldl (fun count k =>
        let occurrences := (nStr.splitOn k).length - 1
        if occurrences > 0 then count + 100 + (occurrences - 1) else count
      ) 0
      if score > 0 then acc.push (name, info, score) else acc

  let sortedMatches := matchesArray.qsort fun (n1, _, s1) (n2, _, s2) =>
    if s1 != s2 then s1 > s2
    else
      let str1 := n1.toString
      let str2 := n2.toString
      if str1.length != str2.length then str1.length < str2.length
      else str1 < str2

  let topMatches := sortedMatches.toList.take 10
  if topMatches.isEmpty then
    return s!"No theorems found matching any of: {keywords}"

  let mut result := ""
  for (name, info, _) in topMatches do
    try
      let type ← Meta.ppExpr info.type
      result := result ++ s!"{name} : {type}\n"
    catch _ => continue
  return result

structure SearchRequest where
  query : String
  deriving ToJson

structure SearchResponse where
  results : String
  success : Bool
  message : String
  deriving FromJson

unsafe def findTheoremsWeb (keywords : String) : TacticM String := do
  logInfo "[Search] Using leansearch.net provider..."
  let req : SearchRequest := { query := keywords }
  
  let res : SearchResponse ← runIO (callPythonService req #["--task", "search"])

  if res.success then 
    return res.results
  else 
    throwError s!"[Web Search Error] {res.message}"

unsafe def findTheorems (keywords : String) : TacticM String := do
  if keywords == "NONE" || keywords == "" then return "No search performed."

  let provider ← runIO getSearchProviderFromEnv
  match provider with
  | .localEnv => findTheoremsLocal keywords
  | .leanSearchNet => findTheoremsWeb keywords
