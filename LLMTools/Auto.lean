import LLMTools.Tactic

open Lean Meta Elab Tactic

structure AutoPlan where
  type : String
  plan : List String
  deriving FromJson

unsafe def runChainMode (plan : List String) (stx : Syntax) : TacticM Unit := do
  let finalCode ← withoutModifyingState do
    let mut codeAccum := ""
    for step in plan do
      logInfo s!"[Auto Chain] Processing: {step}"
      try
        let stepCode ← runChainStep step stx
        codeAccum := codeAccum ++ stepCode ++ "\n"
      catch e =>
        let m ← e.toMessageData.toString
        logWarning s!"[Auto Chain] Step failed: {m}."
        break

    return codeAccum

  if !finalCode.isEmpty then
    Lean.Meta.Tactic.TryThis.addSuggestion stx finalCode


syntax (name := llm_auto) "llm_auto" (ppSpace str)? : tactic
@[tactic llm_auto] unsafe def evalLlmAuto : Tactic := fun stx => do
  let hint? := match stx with
    | `(tactic| llm_auto $[$s:str]?) => s.map (·.getString)
    | _ => none

  let mainGoal ← getMainGoal
  let goalState ← mainGoal.withContext do return (← ppGoal mainGoal).pretty
  let ctx ← readThe Core.Context

  let req : LlmRequest := {
    requestType := "init_auto",
    goalState := goalState,
    source := ctx.fileMap.source,
    pos := stx.getPos?.map (·.byteIdx),
    hint := hint?,
    prevTactic := none, errorMsg := none, searchResults := none, diagnosisInfo := none
  }

  let res : LlmResponse ← runIO (callPythonService req)

  let planData? : Option AutoPlan := do
    let analysisStr ← res.analysis
    let json ← Json.parse analysisStr |>.toOption
    FromJson.fromJson? json |>.toOption

  match planData? with
  | some planData =>
    if planData.type == "CHAIN" then
      logInfo s!"[Auto] Detected CHAIN structure with {planData.plan.length} steps."
      runChainMode planData.plan stx
    else
      logInfo "[Auto] Detected COMPOUND structure. Delegating to Framework."
      let aiPlanStr := String.intercalate "\n- " planData.plan
      let combinedHint := match hint? with
        | some h => s!"[User Hint]: {h}\n\n[Architect's Plan]:\n- {aiPlanStr}"
        | none   => s!"[Architect's Plan]:\n- {aiPlanStr}"
      runInteractiveLlm stx .Framework none (some (Lean.Syntax.mkStrLit combinedHint))

  | none =>
    logWarning "[Auto] Failed to parse plan. Defaulting to Framework."
    runInteractiveLlm stx .Framework none (hint?.map (Lean.Syntax.mkStrLit))
