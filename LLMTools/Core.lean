import Lean

open Lean System

inductive WorkType where
  | Next
  | Framework
  | TypeGen
  | Revise
  | Fallback
  deriving Inhabited, BEq, Repr

instance : ToString WorkType where
  toString
    | .Next      => "next"
    | .Framework => "framework"
    | .TypeGen   => "type"
    | .Revise    => "revise"
    | .Fallback  => "fallback"

inductive WorkPhase where
  | Init
  | Diagnose
  | Fix
  deriving Inhabited, BEq, Repr

instance : ToString WorkPhase where
  toString
    | .Init     => "init"
    | .Diagnose => "diagnose"
    | .Fix      => "fix"

def WorkType.defaultFuel : WorkType → Nat
  | .Next      => 6
  | .Framework => 3
  | .TypeGen   => 4
  | .Revise    => 5
  | .Fallback  => 3

structure LlmRequest where
  requestType   : String
  goalState     : String
  source        : Option String
  pos           : Option Nat
  hint          : Option String
  prevTactic    : Option String
  errorMsg      : Option String
  searchResults : Option String
  diagnosisInfo : Option String
  deriving ToJson

structure LlmResponse where
  tactic      : String
  searchQuery : Option String
  analysis    : Option String
  success     : Bool
  message     : String
  deriving FromJson

def getRequestStr (wType : WorkType) (phase : WorkPhase) : String :=
  match phase with
  | .Diagnose => "diagnose"
  | _ => s!"{phase}_{wType}"

def getLogPrefix (wType : WorkType) : String :=
  s!"[llm_{wType}]"

unsafe def runIO {α : Type} (act : IO α) : Elab.Tactic.TacticM α := do
  match unsafeIO act with
  | Except.ok a => return a
  | Except.error e => throwError s!"[IO Error]: {e}"

def findPythonScriptPath : IO String := do

  if let some envPath ← IO.getEnv "LEAN_LLM_SCRIPT_PATH" then
    if ← FilePath.pathExists envPath then
      return envPath

  let relativePath : FilePath := "LLMService" / "llm_service.py"
  if ← FilePath.pathExists relativePath then
    return relativePath.toString

  let lakePackagesDir : FilePath := ".lake" / "packages"

  if ← lakePackagesDir.pathExists then
    let entries ← System.FilePath.readDir lakePackagesDir
    for entry in entries do
      if ← FilePath.isDir entry.path then
        -- .lake/packages/<PackageName>/LLMService/llm_service.py
        let candidate := entry.path / relativePath
        if ← candidate.pathExists then
          return candidate.toString

  throw <| IO.userError <|
    s!"[LLMTools] Could not locate 'llm_service.py'.\n" ++
    s!"Searched in:\n" ++
    s!"  1. $LEAN_LLM_SCRIPT_PATH\n" ++
    s!"  2. ./{relativePath}\n" ++
    s!"  3. ./.lake/packages/*/{relativePath}\n\n" ++
    "Please ensure the package is built or set LEAN_LLM_SCRIPT_PATH as the path of LLMService/llm_service.py."

def callPythonService {α β : Type} [ToJson α] [FromJson β] (req : α) (extraArgs : Array String := #[]) : IO β := do
  let jsonStr := (ToJson.toJson req).compress ++ "\n"
  let scriptPath ← findPythonScriptPath

  let pythonCmd ← IO.getEnv "LEAN_LLM_PYTHON"
  let args := #[scriptPath] ++ extraArgs

  let child ← IO.Process.spawn {
    cmd := pythonCmd.getD "python3"
    args := args
    stdin := IO.Process.Stdio.piped
    stdout := IO.Process.Stdio.piped
    stderr := IO.Process.Stdio.inherit
  }
  let (stdin, child) ← child.takeStdin
  stdin.putStr jsonStr
  stdin.flush
  let outputTask ← IO.asTask child.stdout.readToEnd Task.Priority.dedicated
  let _ ← child.wait
  let outStr ← IO.ofExcept outputTask.get

  match Json.parse outStr with
  | Except.ok json =>
    match FromJson.fromJson? json with
    | Except.ok res => return res
    | Except.error e => throw <| IO.userError s!"JSON decode error: {e}"
  | Except.error e => throw <| IO.userError s!"JSON parse error: {e}. Output: {outStr}"
