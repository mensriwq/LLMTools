import Lean.Parser.Tactic
import Lean.Elab.Term
import Lean.Elab.Tactic.Basic
import Lean.Elab.SyntheticMVars
import Lean.Meta.Tactic.TryThis

import LLMTools.Search

open Lean Meta Elab Tactic

def callLlmService (req : LlmRequest) : IO LlmResponse :=
  callPythonService req #[]

def runStrictCheck (tacticStx : Syntax) : TacticM Unit := do
  withoutModifyingState do
    let coreState ← getThe Core.State
    let oldMsgs := coreState.messages
    try
      modifyThe Core.State fun s => { s with messages := {} }
      evalTactic tacticStx
      Term.synthesizeSyntheticMVarsNoPostponing
      let newCoreState ← getThe Core.State
      let msgs := newCoreState.messages.toList
      let mut collectedErrors : List String := []
      for m in msgs do
        let msgStr ← Core.liftIOCore m.toString
        if m.severity == MessageSeverity.error then
          if !(msgStr.toSlice.contains "unsolved goals" || msgStr.toSlice.contains "No goals to be solved") then
            collectedErrors := collectedErrors.concat msgStr
      if !collectedErrors.isEmpty then
        throwError s!"\n".intercalate collectedErrors
    finally
      modifyThe Core.State fun s => { s with messages := oldMsgs }

unsafe def llmFuelLoop (fuel : Nat) (wType : WorkType) (phase : WorkPhase) (req : LlmRequest) (stx : Syntax) : TacticM Unit := do
  if fuel == 0 then
    match wType with
    | .Fallback =>
      throwError "[LLM] Fallback failed. Unable to salvage the proof."
    | _ =>
      logWarning s!"{getLogPrefix wType} Fuel exhausted. Switching to FALLBACK mode..."

      let prevCode := req.prevTactic.getD "sorry"
      let prevErr := req.errorMsg.getD "Timeout"

      let fallbackReq := { req with
        requestType := "fallback",
        prevTactic := some prevCode,
        errorMsg := some prevErr
      }
      llmFuelLoop (WorkType.defaultFuel .Fallback) .Fallback .Fix fallbackReq stx
      return

  let currentReq := { req with requestType := getRequestStr wType phase }
  let logPrefix := getLogPrefix wType

  let res ← runIO (callLlmService currentReq)
  if ¬res.success then throwError s!"Service Error: {res.message}"

  if phase == .Diagnose then
    let query := res.searchQuery.getD "NONE"
    let analysis := res.analysis.getD "No analysis provided."
    let searchResults ← findTheorems query

    logInfo s!"[Diagnosis] Analysis: {analysis}"
    if query != "NONE" then logInfo s!"[Search] Found:\n{searchResults}"

    let fixReq := { req with
      searchResults := some searchResults,
      diagnosisInfo := some analysis
    }
    llmFuelLoop fuel wType .Fix fixReq stx
    return

  let tacticCode := res.tactic

  if res.message == "Returned from Cache" then
    logInfo s!"{logPrefix} ⚡ Using cached suggestion."
  else
    logInfo s!"{logPrefix} Trying:\n{tacticCode}"

  match Parser.runParserCategory (← getEnv) `tactic ("{\n" ++ tacticCode ++ "\n}") with
  | Except.error e =>
    logWarning s!"{logPrefix}{e} Syntax error. Retrying..."
    let newReq := { req with prevTactic := some tacticCode, errorMsg := some s!"Syntax Error: {e}" }
    llmFuelLoop (fuel - 1) wType .Fix newReq stx

  | Except.ok tacticStx =>
    let checkRes ← (try
        runStrictCheck tacticStx
        pure (Except.ok ())
      catch e =>
        pure (Except.error e))

    match checkRes with
    | Except.ok _ =>
      let tacticSyntax : TSyntax `tactic := ⟨tacticStx⟩
      TryThis.addSuggestion stx { suggestion := tacticSyntax }
      logInfo s!"{logPrefix} Verification Passed!"

      let successReq := { req with
        requestType := "report_success",
        prevTactic := some tacticCode,
        diagnosisInfo := some (toString wType)
      }

      let _ ← runIO (callLlmService successReq)

    | Except.error e =>
      let msg ← e.toMessageData.toString
      logWarning s!"{logPrefix} Logic Check Failed: {msg}"
      let diagReq := { req with
        prevTactic := some tacticCode,
        errorMsg := some msg
      }
      llmFuelLoop (fuel - 1) wType .Diagnose diagReq stx

unsafe def runLlmTactic (stx : Syntax) (wType : WorkType) (num? : Option (TSyntax `num)) (str? : Option (TSyntax `str)) : TacticM Unit := do
  runIO (IO.sleep 500)

  let fuel := match num? with
    | some nStx => nStx.getNat
    | none      => wType.defaultFuel

  let hint? := match str? with
    | some sStx => some sStx.getString
    | none      => none

  let mainGoal ← getMainGoal
  let goalState ← mainGoal.withContext do return (← ppGoal mainGoal).pretty
  let ctx ← readThe Core.Context
  let source := ctx.fileMap.source
  let pos := stx.getPos?.map (·.byteIdx)

  let initialReq : LlmRequest := {
    requestType := "",
    goalState := goalState,
    source := source,
    pos := pos,
    hint := hint?,
    prevTactic := none,
    errorMsg := none,
    searchResults := none,
    diagnosisInfo := none
  }

  llmFuelLoop fuel wType .Init initialReq stx

-- Syntax: llm_next <fuel?> <hint?>
syntax (name := llm_next) "llm_next" (ppSpace num)? (ppSpace str)? : tactic

@[tactic llm_next] unsafe def evalLlmNext : Tactic := fun stx => do
  match stx with
  | `(tactic| llm_next $[$n:num]? $[$s:str]?) =>
    runLlmTactic stx .Next n s
  | _ => throwUnsupportedSyntax

-- Syntax: llm_framework <fuel?> <hint?>
syntax (name := llm_framework) "llm_framework" (ppSpace num)? (ppSpace str)? : tactic

@[tactic llm_framework] unsafe def evalLlmframework : Tactic := fun stx => do
  match stx with
  | `(tactic| llm_framework $[$n:num]? $[$s:str]?) =>
    runLlmTactic stx .Framework n s
  | _ => throwUnsupportedSyntax


-- Syntax: llm_type <fuel?> <hint?>
syntax (name := llm_type) "llm_type" (ppSpace num)? (ppSpace str)? : tactic

@[tactic llm_type] unsafe def evalLlmType : Tactic := fun stx => do
  match stx with
  | `(tactic| llm_type $[$n:num]? $[$s:str]?) =>
    runLlmTactic stx .TypeGen n s
  | _ => throwUnsupportedSyntax

-- Syntax: llm_revise <fuel?> <old_code>
syntax (name := llm_revise) "llm_revise" (ppSpace num)? (ppSpace str) : tactic

@[tactic llm_revise] unsafe def evalLlmRevise : Tactic := fun stx => do
  match stx with
  | `(tactic| llm_revise $[$n:num]? $s) =>
    runLlmTactic stx .Revise n s
  | _ => throwUnsupportedSyntax
