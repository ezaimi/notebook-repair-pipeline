/* Repair Workspace: replays one notebook's recorded pipeline trace as a
   sequence of stages. Round 1 always runs the same six stages. If Round 1's
   re-execution exposed a genuinely new error, a Round-2 section opens:
   the new error is reclassified, explained as its own record, and only a
   record whose classification makes it repair-eligible goes on to
   RAGRepairAgent and FixApplicator. Eligibility is not a component: it is
   the orchestrator's decision derived from the classification, shown as a
   small gate between the explanation and the repair nodes. Two rounds is
   the hard cap. */

const wsState = { caseId: null, flat: 0, direction: 1, transitioning: false };
let wsCase = null;
let wsPlaybackTimer = null;

const ROOT_CAUSE_TEXT = {
  import_distribution_name_mismatch:
    "Classified as a missing package whose import name differs from its PyPI distribution name.",
  direct_missing_package:
    "Classified as a missing package, with no indication that the import name differs from its PyPI distribution name.",
  version_or_api_incompatibility:
    "Classified as a version/API incompatibility: the package is installed, but an expected symbol is missing — consistent with an API change between releases.",
  system_level_dependency:
    "Classified as a missing system-level (shared) library. Installing a Python package cannot fix this, so it is outside the pip-only repair scope.",
  local_import_or_path_issue:
    "Classified as an ambiguous local import or module-path problem, which the repair layer cannot resolve against PyPI.",
  insufficient_context:
    "The recorded error carries too little information to decide a more specific root cause.",
};

const SKIP_REASON_TEXT = {
  input_status_not_success: "The repair agent abstained, so there was no proposal for FixApplicator to apply.",
};

const FAILURE_STAGE_TEXT = {
  clone: "the repository could not be cloned while rebuilding the Docker execution environment",
  checkout: "the target commit could not be checked out while rebuilding the Docker execution environment",
  build: "the Docker image failed to build",
  timeout: "the container run exceeded its time budget",
  join: "an internal dataset-join step failed before the fix could be applied",
  validation: "the proposal failed re-validation before it could be applied",
  notebook_execution: "the notebook file could not be found / executed inside the rebuilt container",
};

const TRIGGER_REASON_TEXT = {
  round1_outcome_not_still_failing: "Round 1 did not end in still_failing (it abstained or could not be applied), so there is no new error to carry forward.",
  same_as_original_error: "The error after repair is the same error the repair targeted, so a second round would test nothing new.",
  new_dependency_error_eligible: "The newly exposed error was reclassified as a pip-repairable dependency error, so a second bounded repair round runs on it.",
  "new_error_not_repair_eligible:excluded": "The newly exposed error was reclassified outside the pip-only repair scope. It was explained, but no repair round was started for it.",
};

// ---------------------------------------------------------------------
// Stage model
// ---------------------------------------------------------------------

function ragState(r) {
  if (r.repair_agent.status === "success") return "completed";
  if (r.repair_agent.status === "abstained") return "abstained";
  return "failed";
}
function fixState(r) {
  if (!r.fix_applicator.attempted) return "skipped";
  if (r.fix_applicator.outcome === "apply_error") return "failed";
  return "completed";
}
function explState(e) {
  return e && e.status === "success" ? "completed" : "failed";
}

// Every stage of the recorded trace, in replay order.
function stagesFor(c) {
  const r1 = c.rounds[0];
  const stages = [
    { key: "failure", round: 1, label: "Original Failure", state: "completed" },
    { key: "classifier", round: 1, label: "Classification", state: "completed" },
    { key: "explanation", round: 1, label: "LLM Explanation", state: explState(c.explanation) },
    { key: "rag", round: 1, label: "Retrieval & Repair Proposal", state: ragState(r1) },
    { key: "fix", round: 1, label: "Fix Application", state: fixState(r1) },
    { key: "reexec", round: 1, label: "Re-execution", state: fixState(r1) },
  ];
  if (c.round2) {
    const r2 = c.rounds[1];
    stages.push(
      { key: "new_error", round: 2, label: "Newly Exposed Failure", state: "completed" },
      { key: "reclassify", round: 2, label: "Reclassification", state: "completed" },
      { key: "explanation2", round: 2, label: "New Explanation", state: explState(c.round2.explanation) },
    );
    if (r2) {
      stages.push(
        { key: "rag", round: 2, label: "Retrieval & Repair Proposal", state: ragState(r2) },
        { key: "fix", round: 2, label: "Fix Application", state: fixState(r2) },
        { key: "reexec", round: 2, label: "Re-execution", state: fixState(r2) },
      );
    }
  }
  stages.push({ key: "final", round: c.round2 ? 2 : 1, label: "Final Result", state: "completed", final: true });
  return stages;
}

function roundFor(c, stage) {
  return c.rounds.find(r => r.round === stage.round) || c.rounds[0];
}

// ---------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------

function renderWorkspace(caseId, stepArg) {
  if (!caseId) caseId = wsState.caseId || (CASES.find(c => c.showcase) || CASES[0]).id;
  if (wsState.caseId !== caseId) {
    stopWorkspacePlayback();
    wsState.caseId = caseId;
    wsState.flat = 0;
    wsState.direction = 1;
    wsState.transitioning = false;
  }
  // optional deep link: #/workspace/<case>/<stage index, 1-based>
  if (stepArg !== undefined && /^\d+$/.test(String(stepArg))) wsState.flat = parseInt(stepArg, 10) - 1;
  const c = CASES.find(x => x.id === caseId);
  wsCase = c;
  if (!c) {
    document.getElementById("main").innerHTML = `<div class="empty-note">Case "${esc(caseId)}" not found.</div>`;
    return;
  }

  const stages = stagesFor(c);
  wsState.flat = Math.max(0, Math.min(wsState.flat, stages.length - 1));
  const stage = stages[wsState.flat];
  const playing = !!wsPlaybackTimer;
  const r1Stages = stages.filter(s => s.round === 1 && !s.final);
  const r2Stages = stages.filter(s => s.round === 2 && !s.final);
  const finalIdx = stages.length - 1;
  const r1ReexecIdx = stages.findIndex(s => s.key === "reexec" && s.round === 1);
  const round2Open = !!c.round2 && wsState.flat > r1ReexecIdx;

  const html = `
    <div class="workspace-header">
      <div class="workspace-title-block">
        <div class="eyebrow">Repair Workspace &middot; Notebook #${c.notebook_execution_id} &middot; ${esc(repoShortName(c.repository_url))}</div>
        <h1>${esc(c.original_error.error_type)}: ${esc(c.original_error.failing_module)}</h1>
        <div class="repo-link">${labelize(c.rounds[0].classifier.subtype)} &middot; ${esc(c.notebook_name || "")}</div>
      </div>
      <div class="workspace-header-actions">
        ${c.showcase ? `<span class="badge badge-accent" title="${esc(c.showcase)}">Showcase case</span>` : ""}
        ${round2Badge(c)}
        <span class="recorded-run-badge"><span class="dot"></span> Recorded run &middot; Gemma-2 9B</span>
      </div>
    </div>

    <section class="journey-shell ${wsState.transitioning ? "journey-transitioning" : ""}">
      <div class="journey-topline">
        <div>
          <div class="journey-eyebrow">Recorded execution path</div>
          <div class="journey-current">${esc(stage.label)}${stage.final ? "" : ` <span class="journey-round-tag">Round ${stage.round}</span>`}</div>
        </div>
        <div class="journey-meta">
          <span>${wsState.flat + 1} / ${stages.length}</span>
          <span>${c.round2 ? "2 rounds" : "1 round"} &middot; cap 2</span>
        </div>
      </div>

      <div class="journey-row">
        <div class="journey-row-label"><span class="journey-round-pill">Round 1</span><span>Original failure</span></div>
        <div class="journey-track">${trackHtml(stages, r1Stages, stage)}</div>
      </div>

      ${c.round2 ? `
        <div class="journey-loop ${round2Open ? "open" : "closed"}">
          <div class="journey-loop-arrow">
            <span class="journey-loop-glyph">&#8617;</span>
            <span>Re-execution exposed a <strong>new</strong> error &rarr; reclassified &rarr; explained &rarr; eligibility checked &rarr; repaired only if eligible</span>
          </div>
          <div class="journey-row journey-row-r2">
            <div class="journey-row-label"><span class="journey-round-pill r2">Round 2</span><span>Newly exposed error</span></div>
            <div class="journey-track">${trackHtml(stages, r2Stages, stage)}</div>
          </div>
        </div>` : `
        <div class="journey-noloop">${noRound2Text(c)}</div>`}

      <div class="journey-row journey-final-row">
        <div class="journey-row-label"><span class="journey-round-pill">Outcome</span><span>Hard cap: 2 rounds</span></div>
        <div>${finalNodeHtml(stages[finalIdx], finalIdx, stage === stages[finalIdx], wsState.flat > finalIdx, c)}</div>
      </div>

      <div class="journey-caption">
        <span class="journey-caption-pulse"></span>
        ${esc(journeyCaption(c, stage))}
      </div>
    </section>

    <div class="workspace-body workspace-body-live">
      <div class="workspace-main-column">
        <div class="step-panel stage-panel" id="step-panel"></div>
        <div class="presentation-toolbar execution-controls">
          <button class="btn" id="btn-prev">&larr; Previous</button>
          <div class="playback-controls">
            <button class="btn btn-replay" id="btn-reset" title="Return to the first recorded event">Reset</button>
            <button class="btn btn-primary btn-play" id="btn-play">${playing ? "Pause Replay" : "Play Replay"}</button>
            <span class="small-caps" id="progress-label">Step ${wsState.flat + 1} of ${stages.length}</span>
          </div>
          <button class="btn btn-primary" id="btn-next">Next &rarr;</button>
        </div>
      </div>

      <aside class="execution-rail">
        ${storyCardHtml(c, stages)}
        ${finalResultCardHtml(c)}
      </aside>
    </div>
  `;
  document.getElementById("main").innerHTML = html;

  document.getElementById("btn-prev").addEventListener("click", () => stepBy(-1));
  document.getElementById("btn-next").addEventListener("click", () => stepBy(1));
  document.getElementById("btn-reset").addEventListener("click", resetWorkspaceReplay);
  document.getElementById("btn-play").addEventListener("click", toggleWorkspacePlayback);
  document.querySelectorAll("[data-flat-index]").forEach(node => {
    node.addEventListener("click", () => {
      stopWorkspacePlayback();
      goToFlat(parseInt(node.dataset.flatIndex, 10));
    });
  });

  renderStepPanel(c, stages, stage);
  document.getElementById("btn-prev").disabled = wsState.flat <= 0;
  document.getElementById("btn-next").disabled = wsState.flat >= stages.length - 1;

  window.setTimeout(() => {
    const shell = document.querySelector(".journey-shell");
    if (shell) shell.classList.remove("journey-transitioning");
    wsState.transitioning = false;
  }, 700);
}

function round2Badge(c) {
  if (!c.round2) return "";
  if (c.round2.repair_status === "attempted") return '<span class="badge badge-r2">Round 2 repaired</span>';
  if (c.round2.repair_status === "abstained") return '<span class="badge badge-warn">Round 2 abstained</span>';
  return '<span class="badge badge-neutral">Round 2: explained only</span>';
}

function noRound2Text(c) {
  const r1 = c.rounds[0];
  const reason = r1.round2_trigger.reason;
  if (reason === "same_as_original_error") return "No second round: the repair was applied but the identical error persisted, so there was no new error to carry forward.";
  if (r1.repair_agent.status === "abstained") return "No second round: Round 1 abstained before any repair was applied, so nothing was re-executed.";
  if (r1.fix_applicator.outcome === "apply_error") return "No second round: the fix could not be applied, so the notebook was never re-executed.";
  return "No second round was needed.";
}

function trackHtml(all, subset, current) {
  return subset.map((s, i) => {
    const flat = all.indexOf(s);
    const isActive = s === current;
    const isPast = flat < wsState.flat;
    const isFuture = flat > wsState.flat;
    const cls = ["journey-node", `state-${s.state}`, isActive ? "active" : "", isPast ? "visited" : "", isFuture ? "future" : ""].filter(Boolean).join(" ");
    const isExplanation = s.key === "explanation" || s.key === "explanation2";
    const hasNext = i < subset.length - 1;
    const connector = (hasNext || isExplanation)
      ? `<div class="journey-connector ${flat < wsState.flat ? "complete" : ""} ${flat === wsState.flat - 1 && wsState.direction > 0 ? "edge-travel" : ""}">
           <div class="journey-line"></div><span class="journey-packet"></span>
         </div>`
      : "";
    // The repair-eligibility decision is derived from the classification of
    // this round's record; it is drawn as a small gate, not as a component.
    const gate = isExplanation ? gateHtml(wsCase, s.round, flat) : "";
    return `
      <button class="${cls}" data-flat-index="${flat}" aria-label="Open ${esc(s.label)}">
        <span class="journey-node-icon">${stageIcon(s.key)}</span>
        <span class="journey-node-copy">
          <span class="journey-node-title">${esc(shortStageLabel(s))}</span>
          <span class="journey-node-sub">${esc(stageSubLabel(wsCase, s))}</span>
        </span>
        <span class="journey-node-state">${stageStateMark(s.state, isPast, isActive)}</span>
      </button>${connector}${gate}`;
  }).join("");
}

// Eligibility gate for one round: eligible -> a small "repair-eligible" pill
// followed by a connector into RAG + PyPI; not eligible -> a "not
// repair-eligible" pill and a stop marker, nothing after it.
function eligibilityOf(c, round) {
  if (round === 1) {
    const cls = c.rounds[0].classifier;
    return { eligible: cls.scope_status === "usable", subtype: cls.subtype, scope: cls.scope_status };
  }
  return { eligible: !!c.round2.eligible, subtype: c.round2.record.subtype, scope: c.round2.record.scope_status };
}

function gateHtml(c, round, explanationFlat) {
  const g = eligibilityOf(c, round);
  const reached = wsState.flat > explanationFlat;
  const stateCls = reached ? "reached" : "future";
  if (g.eligible) {
    return `
      <div class="journey-gate ok ${stateCls}" title="Decided by the orchestrator from the classification: ${esc(labelize(g.subtype))}, scope ${esc(g.scope)}">
        <span class="gate-mark">&#10003;</span>
        <span class="gate-text">repair-<br/>eligible</span>
      </div>
      <div class="journey-connector ${reached ? "complete" : ""}">
        <div class="journey-line"></div><span class="journey-packet"></span>
      </div>`;
  }
  return `
    <div class="journey-gate stop ${stateCls}" title="Decided by the orchestrator from the classification: ${esc(labelize(g.subtype))}, scope ${esc(g.scope)}">
      <span class="gate-mark">&#10007;</span>
      <span class="gate-text">not repair-<br/>eligible</span>
    </div>
    <div class="journey-stop ${stateCls}"><span class="stop-glyph">&#9632;</span><span>stop</span></div>`;
}

function finalNodeHtml(stage, flat, isActive, isPast, c) {
  const cat = c.final_result.final_category;
  return `
    <button class="journey-node journey-node-final state-completed ${isActive ? "active" : ""} ${flat < wsState.flat ? "visited" : ""} ${flat > wsState.flat ? "future" : ""}" data-flat-index="${flat}">
      <span class="journey-node-icon">&#9873;</span>
      <span class="journey-node-copy">
        <span class="journey-node-title">Final result</span>
        <span class="journey-node-sub">${esc(labelize(cat))}</span>
      </span>
      <span class="journey-node-state">${isActive ? '<span class="state-ring"></span>' : ""}</span>
    </button>`;
}

function stageIcon(key) {
  return { failure: "!", new_error: "!", classifier: "C", reclassify: "C", explanation: "LLM", explanation2: "LLM",
           rag: "RAG", fix: "FIX", reexec: "▶", final: "⚑" }[key] || "•";
}

function shortStageLabel(s) {
  return { failure: "Original failure", new_error: "New error", classifier: "Classifier", reclassify: "Reclassify",
           explanation: "LLM explanation", explanation2: "New explanation",
           rag: "RAG + PyPI", fix: "FixApplicator", reexec: "Docker re-run", final: "Final result" }[s.key] || s.label;
}

function stageSubLabel(c, s) {
  const r = roundFor(c, s);
  switch (s.key) {
    case "failure": return "Captured notebook error";
    case "new_error": return "From Round-1 re-execution";
    case "classifier": return labelize(r.classifier.subtype);
    case "reclassify": return `${labelize(c.round2.record.subtype)} · ${c.round2.record.scope_status}`;
    case "explanation": return c.explanation.status === "success" ? "Plain-language cause" : "No response (runtime)";
    case "explanation2": return c.round2.explanation.status === "success" ? "Explains the new error" : "No response (runtime)";
    case "rag": return r.retrieval && r.retrieval.status === "resolved" ? "Grounded package evidence" : "Safe abstention";
    case "fix": return r.fix_applicator.attempted ? "Apply proposed command" : "No command applied";
    case "reexec": return "Validate in container";
    default: return "";
  }
}

function stageStateMark(state, isPast, isActive) {
  if (isActive) return '<span class="state-ring"></span>';
  if (isPast && state === "completed") return "✓";
  if (state === "abstained") return "A";
  if (state === "failed") return "×";
  if (state === "skipped") return "–";
  return "";
}

function journeyCaption(c, s) {
  const r = roundFor(c, s);
  switch (s.key) {
    case "failure": return `The recorded failure enters the repair layer: ${c.original_error.error_type} on ${c.original_error.failing_module}.`;
    case "classifier": return `ErrorClassifier labels ${r.classifier.failing_module} as ${labelize(r.classifier.subtype)} and decides repair scope before any model is called; repair eligibility follows from that decision.`;
    case "explanation": return c.explanation.status === "success"
      ? "LLMExplainer turns the classified failure into a plain-language explanation. It never proposes a fix and is not passed to the repair agent."
      : "The explanation call returned no processable response within its retry budget. The repair path continues regardless.";
    case "rag": return r.repair_agent.status === "success"
      ? "The import is mapped to a PyPI distribution, live release evidence is retrieved, and the model chooses a grounded repair from that evidence."
      : "No grounded package candidate is available for this import, so the repair agent abstains before calling the model.";
    case "fix": return r.fix_applicator.attempted
      ? (s.round === 2 ? "Round 1's validated command is replayed in a fresh container, then the Round-2 command is applied on top."
                       : "The validated pip command is applied inside a rebuilt Docker environment.")
      : "No repair command is executed because there was no applicable proposal.";
    case "reexec": return "The notebook is executed top-to-bottom to see whether the targeted dependency error is gone.";
    case "new_error": return "Round 1 removed its targeted error, but re-execution stopped on a different error. That error becomes a record of its own.";
    case "reclassify": return "The new error goes through the same two classifier stages as an original failure.";
    case "explanation2": return c.round2.eligible
      ? "LLMExplainer explains the newly exposed error, separately from the original failure. Its reclassification makes it repair-eligible, so the second round continues into repair."
      : "LLMExplainer explains the newly exposed error, separately from the original failure. Its reclassification puts it outside the pip-only repair scope, so the second round stops here.";
    case "final": return "Two rounds is the hard cap. Whatever error remains after this point is recorded but not repaired.";
    default: return "Recorded pipeline event.";
  }
}

// ---------------------------------------------------------------------
// Navigation / playback
// ---------------------------------------------------------------------

function goToFlat(target) {
  const stages = stagesFor(wsCase);
  if (target < 0 || target >= stages.length) return;
  wsState.direction = target >= wsState.flat ? 1 : -1;
  wsState.flat = target;
  wsState.transitioning = true;
  renderWorkspace(wsState.caseId);
}

function stepBy(delta) {
  if (!wsCase) return;
  const stages = stagesFor(wsCase);
  const next = wsState.flat + delta;
  if (next < 0 || next >= stages.length) {
    if (wsPlaybackTimer) stopWorkspacePlayback();
    return;
  }
  goToFlat(next);
}

function toggleWorkspacePlayback() {
  if (wsPlaybackTimer) {
    stopWorkspacePlayback();
    renderWorkspace(wsState.caseId);
    return;
  }
  const stages = stagesFor(wsCase);
  if (wsState.flat >= stages.length - 1) {
    wsState.flat = 0;
    wsState.transitioning = false;
  }
  wsPlaybackTimer = window.setInterval(() => {
    if (!window.location.hash.includes("/workspace")) { stopWorkspacePlayback(); return; }
    const n = stagesFor(wsCase).length;
    if (wsState.flat >= n - 1) { stopWorkspacePlayback(); renderWorkspace(wsState.caseId); return; }
    stepBy(1);
  }, 1650);
  renderWorkspace(wsState.caseId);
}

function stopWorkspacePlayback() {
  if (wsPlaybackTimer) { window.clearInterval(wsPlaybackTimer); wsPlaybackTimer = null; }
}

function resetWorkspaceReplay() {
  stopWorkspacePlayback();
  wsState.flat = 0;
  wsState.direction = 1;
  wsState.transitioning = false;
  renderWorkspace(wsState.caseId);
}

// ---------------------------------------------------------------------
// Step panel
// ---------------------------------------------------------------------

function renderStepPanel(c, stages, stage) {
  const el = document.getElementById("step-panel");
  const r = roundFor(c, stage);
  let body = "";
  switch (stage.key) {
    case "failure": body = stepFailure(c); break;
    case "classifier": body = stepClassifier(c, r); break;
    case "explanation": body = stepExplanation(c.explanation, { round: 1, subject: c.original_error }); break;
    case "rag": body = stepRag(c, r); break;
    case "fix": body = stepFix(c, r); break;
    case "reexec": body = stepReexec(c, r, stages); break;
    case "new_error": body = stepNewError(c); break;
    case "reclassify": body = stepReclassify(c); break;
    case "explanation2": body = stepExplanation(c.round2.explanation, { round: 2, subject: c.round2.new_error }); break;
    case "final": body = stepFinal(c); break;
    default: body = `<div class="empty-note">No content.</div>`;
  }
  const inRound = stages.filter(s => s.round === stage.round && !s.final);
  const pos = inRound.indexOf(stage);
  el.innerHTML = `
    <div class="step-panel-head">
      <div>
        <div class="step-kicker">${stage.final ? "Outcome" : `Round ${stage.round} &middot; Stage ${pos + 1} of ${inRound.length}`}${stage.round === 2 && !stage.final ? ' &middot; <span class="r2-kicker">newly exposed error</span>' : ""}</div>
        <h2>${esc(stage.label)}</h2>
      </div>
      <div class="step-panel-state">${stateBadge(stage.state)}</div>
    </div>
    ${body}
  `;
}

function stateBadge(state) {
  return { completed: badge("Completed", "good"), abstained: badge("Abstained", "warn"), failed: badge("Failed", "bad"), skipped: badge("Skipped", "neutral") }[state] || "";
}

function stepFailure(c) {
  const oe = c.original_error;
  const hasRaw = oe.raw_traceback || oe.failing_cell_source;
  return `
    <div class="error-banner">${esc(oe.error_type)}: ${esc(oe.error_message)}</div>
    ${kvGrid([
      ["Notebook Execution ID", `<span class="mono">#${c.notebook_execution_id}</span>`],
      ["Repository", `<a href="${esc(c.repository_url)}" target="_blank" rel="noopener">${esc(repoShortName(c.repository_url))}</a>`],
      ["Notebook", `<span class="mono" style="font-size:12px;">${esc(oe && c.notebook_name)}</span>`],
      ["Error Type", esc(oe.error_type)],
      ["Failing Module", `<span class="mono">${esc(oe.failing_module)}</span>`],
      ["Failing Cell Index", esc(safe(oe.error_cell_index))],
    ])}
    ${hasRaw ? `
      <details class="raw-json">
        <summary>View recorded failing cell / traceback</summary>
        ${oe.failing_cell_source ? `<pre>${esc(oe.failing_cell_source)}</pre>` : ""}
        ${oe.raw_traceback ? `<pre>${esc(oe.raw_traceback)}</pre>` : ""}
      </details>` : `<p class="small-caps" style="margin-top:10px;">Only execution metadata was recorded for this notebook; no raw traceback / cell source is stored.</p>`}
  `;
}

function classifierGrid(cls) {
  const scopeBadge = cls.scope_status === "usable" ? badge("Usable — pip-repairable", "good") : badge(`Excluded — ${cls.scope_status === "excluded" ? "outside pip-only scope" : labelize(cls.scope_status)}`, "warn");
  return kvGrid([
    ["Subtype", `<strong>${esc(labelize(cls.subtype))}</strong>`],
    ["Repair Scope", scopeBadge],
    ["Failing Module", `<span class="mono">${esc(safe(cls.failing_module))}</span>`],
    ["Root-cause Hint", labelize(cls.root_cause_hint)],
    ["Classifier Confidence", cls.confidence ? badge(labelize(cls.confidence), "accent") : "—"],
    ["Context Available", labelize(cls.context_status)],
  ]);
}

function stepClassifier(c, r) {
  const cls = r.classifier;
  const interp = ROOT_CAUSE_TEXT[cls.root_cause_hint] || "";
  return `
    ${classifierGrid(cls)}
    ${interp ? `<div class="interp-text">${esc(interp)}</div>` : ""}
    ${eligibilityDecisionHtml(c, 1)}
    <p class="small-caps">Deterministic rules over the recorded error type and message. No language model is involved in this decision.</p>
  `;
}

// The orchestrator's repair-eligibility decision is a consequence of the
// classification of this round's record (subtype + scope), not a component
// of its own. Explanation always happens; only repair depends on it.
function eligibilityDecisionHtml(c, round) {
  const g = eligibilityOf(c, round);
  const reason = round === 2 ? (TRIGGER_REASON_TEXT[c.round2.trigger_reason] || "") : "";
  const exclusion = round === 2 ? c.round2.record.exclusion_reason : null;
  if (g.eligible) {
    return `
      <div class="gate-callout ok">
        <div class="gate-callout-head"><span class="gate-mark">&#10003;</span> Repair-eligible &mdash; decided from this classification</div>
        <div class="gate-callout-body">
          Subtype <strong>${esc(labelize(g.subtype))}</strong> with scope <span class="mono">${esc(g.scope)}</span> is inside the pip-only repair scope, so after the explanation
          ${round === 2 ? "the second round continues into RAGRepairAgent and FixApplicator, targeting the new error." : "the record proceeds to RAGRepairAgent and FixApplicator."}
          ${reason ? esc(reason) : ""}
        </div>
      </div>`;
  }
  return `
    <div class="gate-callout stop">
      <div class="gate-callout-head"><span class="gate-mark">&#10007;</span> Not repair-eligible &mdash; decided from this classification</div>
      <div class="gate-callout-body">
        Subtype <strong>${esc(labelize(g.subtype))}</strong> with scope <span class="mono">${esc(g.scope)}</span>${exclusion ? ` (${esc(exclusion)})` : ""} is outside the pip-only repair scope.
        The error is still explained; the second round then stops. No RAGRepairAgent call is made, no Round-2 <span class="mono">repair_attempts</span> row is created, and this is not counted as an abstention or as a failure of the explainer.
      </div>
      <div class="gate-chain"><span>Explained</span><span class="gate-arrow">&rarr;</span><span>Not repair-eligible</span><span class="gate-arrow">&rarr;</span><span>No Round-2 repair attempted</span></div>
    </div>`;
}

function stepReclassify(c) {
  const rec = c.round2.record;
  const interp = ROOT_CAUSE_TEXT[rec.root_cause_hint] || "";
  return `
    <div class="callout callout-neutral" style="margin-bottom:12px;">
      The newly exposed error is passed through the <strong>same two classifier stages</strong> as an original failure and becomes a record of its own
      (<span class="mono">context_status: ${esc(rec.context_status)}</span>).
    </div>
    ${classifierGrid(Object.assign({}, rec, { failing_module: rec.failing_module }))}
    ${rec.exclusion_reason ? kvGrid([["Exclusion Reason", esc(rec.exclusion_reason)]]) : ""}
    ${interp ? `<div class="interp-text">${esc(interp)}</div>` : ""}
    ${eligibilityDecisionHtml(c, 2)}
  `;
}

// Renders one recorded LLMExplainer result. `ctx.round` decides the framing:
// Round 2 explains the newly exposed error, never the original failure.
function stepExplanation(e, ctx) {
  const isR2 = ctx.round === 2;
  const subjectBanner = isR2
    ? `<div class="explains-banner r2">
         <div class="explains-label">This explanation describes the <strong>newly exposed</strong> error, not the original failure</div>
         <div class="mono">${esc(ctx.subject.error_type)}: ${esc(ctx.subject.error_message)}</div>
       </div>`
    : `<div class="explains-banner">
         <div class="explains-label">Explains the original failure</div>
         <div class="mono">${esc(ctx.subject.error_type)}: ${esc(ctx.subject.error_message)}</div>
       </div>`;

  if (!e || e.status !== "success") return subjectBanner + explanationUnavailable(e, ctx);

  const j = e.json;
  return `
    ${subjectBanner}
    <div class="explanation-card">
      <div class="sec"><h4>What happened</h4><p>${esc(j.summary)}</p></div>
      <div class="sec"><h4>Why it happened</h4><p>${esc(j.root_cause)}</p></div>
      <div class="sec"><h4>Evidence</h4><ul>${(j.evidence || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="sec"><h4>Limitations</h4><p>${esc(j.limitations)}</p></div>
    </div>
    <hr class="sep" />
    <div class="chip-row">
      ${badge("Completed", "good")}
      ${badge("Schema-valid", "good")}
      ${badge(labelize(j.explanation_confidence) + " confidence", "accent")}
      <span class="small-caps">${esc(e.model_label || e.model)} &middot; ${esc(e.prompt_strategy || "")} &middot; ${e.attempts || 1} attempt${e.attempts === 1 ? "" : "s"}${e.latency_ms ? ` &middot; ${(e.latency_ms / 1000).toFixed(1)} s` : ""}</span>
    </div>
    <p class="small-caps" style="margin-top:8px;">${isR2
      ? "RAGRepairAgent never receives this text, and a failed explanation would not have blocked an eligible repair."
      : "The repair agent never receives this text. Explanation scope is wider than repair scope: an excluded record is still explained."}</p>
    ${isR2 && wsCase && !wsCase.round2.eligible ? `
      <div class="gate-callout stop" style="margin-top:10px;">
        <div class="gate-callout-head"><span class="gate-mark">&#10007;</span> Not repair-eligible &mdash; the second round stops here</div>
        <div class="gate-callout-body">The reclassification placed this error outside the pip-only repair scope (${esc(labelize(wsCase.round2.record.subtype))}, scope <span class="mono">${esc(wsCase.round2.record.scope_status)}</span>). The explanation is kept in the run trace; no Round-2 repair is attempted and no Round-2 <span class="mono">repair_attempts</span> row exists.</div>
        <div class="gate-chain"><span>Explained</span><span class="gate-arrow">&rarr;</span><span>Not repair-eligible</span><span class="gate-arrow">&rarr;</span><span>No Round-2 repair attempted</span></div>
      </div>` : ""}
    <details class="raw-json">
      <summary>View raw explanation JSON</summary>
      <pre>${esc(JSON.stringify(j, null, 2))}</pre>
    </details>
  `;
}

// A record without an explanation failed for a recorded runtime reason - a
// timed-out or unavailable model service - not because the model returned an
// invalid explanation. Say which, and say that repair was not affected.
function explanationUnavailable(e, ctx) {
  const f = (e && e.failure) || {};
  const cat = f.category || f.status || "failed";
  const reasons = (f.validation_errors || []).length ? f.validation_errors : (f.error ? [f.error] : []);
  const text = {
    timeout: `The call to ${esc(e && e.model_label || "the model")} exceeded the 120-second timeout on each attempt, so no explanation text came back.`,
    model_unavailable: `The model service returned an error (recorded as <span class="mono">model_unavailable</span>), so no explanation text came back.`,
  }[cat] || `The LLMExplainer step ended with status <span class="mono">${esc(cat)}</span>.`;
  return `
    <div class="abstain-banner">
      <strong>No explanation was produced${ctx.round === 2 ? " for the newly exposed error" : ""}.</strong><br/>${text}
    </div>
    ${kvGrid([
      ["Failure category", badge(labelize(cat), "warn")],
      ["Attempts", `${safe(f.attempts)}`],
      ...(reasons.length ? [["Recorded reason", `<span class="mono" style="font-size:12px;">${esc(reasons.join("; "))}</span>`]] : []),
    ])}
    <p class="small-caps">
      This is a <strong>runtime failure</strong>, not a schema-invalid response: nothing arrived, so nothing could be validated.
      The repair path is unaffected — it runs from the classifier output, not from the explanation.
    </p>
  `;
}

function stepRag(c, r) {
  const ret = r.retrieval || {};
  const ra = r.repair_agent || {};
  const resolved = ret.status === "resolved";
  const isR2 = r.round === 2;
  const chain = `
    <div class="flow-chain">
      <div class="flow-node"><div class="flabel">Import name</div><div class="fval mono">${esc(ret.import_name || r.classifier.failing_module)}</div></div>
      <div class="flow-sep">&rarr;</div>
      <div class="flow-node"><div class="flabel">Package mapping</div><div class="fval mono">${resolved ? esc(ret.distribution_name) : "Unresolved"}</div></div>
      <div class="flow-sep">&rarr;</div>
      <div class="flow-node"><div class="flabel">PyPI evidence</div><div class="fval">${resolved ? (ret.candidate_versions || []).length + " candidate releases" : "None"}</div></div>
      <div class="flow-sep">&rarr;</div>
      <div class="flow-node"><div class="flabel">Repair LLM</div><div class="fval">${ra.llm_called ? "Called" : "Not called"}</div></div>
      <div class="flow-sep">&rarr;</div>
      <div class="flow-node"><div class="flabel">Grounded proposal</div><div class="fval">${ra.status === "success" ? esc(labelize(ra.action)) : "Abstained"}</div></div>
    </div>
  `;
  const r2Note = isR2 ? `<p class="small-caps" style="margin-bottom:10px;">Round 2 targets the <strong>reclassified new error</strong> (<span class="mono">${esc(r.classifier.failing_module)}</span>) as a record of its own. The Round-2 explanation is not an input here.</p>` : "";

  if (!resolved) {
    const reason = ret.status === "mapping_unknown"
      ? `No supported PyPI distribution mapping exists for the import name <span class="mono">${esc(ret.import_name || r.classifier.failing_module)}</span> in the frozen package-mapping table.`
      : `PyPI retrieval status: ${esc(labelize(ret.status))}.`;
    return `
      ${r2Note}${chain}
      <div class="abstain-banner">
        <strong>Repair safely abstained.</strong><br/>${reason}
        ${(ra.abstain_reasons || []).length ? `<br/><span class="mono" style="font-size:11.5px;">${esc(ra.abstain_reasons.join("; "))}</span>` : ""}
      </div>
      <p class="small-caps">No repair-LLM call was made: the pipeline abstains before invoking the model when there is no grounded package candidate. This is counted as an abstention, not as a failed repair.</p>
    `;
  }

  const compat = ret.compatibility_evidence;
  const cands = (ret.candidate_versions || []).map(v => (v && v.version) ? v.version : v);
  return `
    ${r2Note}${chain}
    ${kvGrid([
      ["Resolved Distribution", `<span class="mono">${esc(ret.distribution_name)}</span>`],
      ["Candidate Releases (newest first)", `<span class="mono" style="font-size:12px;">${esc(cands.join(", "))}</span>`],
      ["Latest PyPI Release", `<span class="mono">${esc(ret.latest_version)}</span>`],
      ["Python Compatibility Target", `<span class="mono">${esc(ret.python_version)}</span>`],
      ["Proposed Action", `<strong>${esc(labelize(ra.action))}</strong>`],
      ["Proposed Package / Version", `<span class="mono">${esc(ra.install_name)}${ra.version ? "==" + esc(ra.version) : ""}</span>`],
      ["Schema Validation", boolBadge(ra.schema_valid, "Passed", "Failed")],
      ["Grounding Validation", boolBadge(ra.grounding_valid, "Passed", "Failed")],
      ["Repair-LLM attempts", `${safe(ra.attempts)}`],
      ["Model", esc(ra.llm_model || "")],
    ])}
    ${ra.rationale ? `<div class="interp-text"><strong>Model rationale:</strong> ${esc(ra.rationale)}</div>` : ""}
    ${compat ? `
      <div class="card" style="background:var(--surface-2); margin-top:14px; box-shadow:none;">
        <div class="card-title" style="margin-bottom:6px;">Version-compatibility evidence &middot; <span class="mono">${esc(compat.compatible_specifier || "")}</span></div>
        <p style="font-size:13px; margin:0 0 6px 0;">${esc(compat.evidence ? compat.evidence.summary : "")}</p>
        ${compat.evidence && compat.evidence.source_url ? `<a href="${esc(compat.evidence.source_url)}" target="_blank" rel="noopener" style="font-size:12px;">${esc(compat.evidence.source_url)}</a>` : ""}
      </div>` : ""}
    <p class="small-caps" style="margin-top:10px;">The model may only choose from the retrieved candidate list; the executable command is built deterministically after validation, never written by the model.</p>
    <details class="raw-json">
      <summary>View raw PyPI retrieval JSON</summary>
      <pre>${esc(JSON.stringify(ret, null, 2))}</pre>
    </details>
  `;
}

function stepFix(c, r) {
  const fa = r.fix_applicator;
  if (!fa.attempted) {
    return `<div class="abstain-banner"><strong>Not executed.</strong><br/>${esc(SKIP_REASON_TEXT[fa.skip_reason] || labelize(fa.skip_reason))}</div>`;
  }
  const isApplyError = fa.outcome === "apply_error";
  const isR2 = r.round === 2;
  const r1cmd = isR2 ? c.rounds[0].fix_applicator.command : null;
  return `
    ${kvGrid([
      ["Action", labelize(r.repair_agent.action)],
      ["Package", `<span class="mono">${esc(r.repair_agent.install_name)}</span>`],
      ["Version", r.repair_agent.version ? `<span class="mono">${esc(r.repair_agent.version)}</span>` : "Not pinned (latest compatible)"],
      ["Command", `<code>${esc(fa.command)}</code>`],
      ["Repository checkout", fa.commit_checkout_status ? `<span class="mono" style="font-size:12px;">${esc(fa.commit_checkout_status)}</span>` : "—"],
      ["Elapsed", fa.elapsed_seconds ? `${fa.elapsed_seconds.toFixed(0)} s` : "—"],
    ])}
    ${isApplyError
      ? applyFailureBlock(c, fa)
      : `<div class="callout callout-neutral">
           ${isR2
             ? `Applied in a <strong>freshly rebuilt</strong> Docker environment. Round 1's validated command
                (<span class="mono">${esc(r1cmd)}</span>) is replayed first, so this round is evaluated as
                <span class="mono">original environment + Round 1 + Round 2</span>, not Round 2 alone.`
             : "Applied inside a Docker environment rebuilt from the same recipe the upstream pipeline uses (python:3.10-slim, requirements.txt, setup.py). The repository was cloned from its default branch."}
         </div>`}
  `;
}

function applyFailureBlock(c, fa) {
  const category = c.final_result.final_category;
  let framing = "";
  if (category === "infrastructure_failure") {
    framing = `Classified as <strong>infrastructure failure</strong>: the recorded evidence points to an external environment/tooling fault, so this record never got a fair trial of the repair.`;
  } else if (category === "method_failure") {
    framing = `Classified as <strong>method failure</strong>: the application could not be judged for a reason that is <em>not</em> unambiguously external. Ambiguous cases are deliberately kept here rather than credited as infrastructure.`;
  }
  return `
    <div class="error-banner" style="font-family:var(--sans);">
      <strong>Fix could not be applied.</strong> ${esc(FAILURE_STAGE_TEXT[fa.failure_stage] || "An environment/tooling fault interrupted this step.")}
      ${fa.diagnostic_message ? `<div class="mono" style="margin-top:6px; font-size:12px;">${esc(fa.diagnostic_message)}</div>` : ""}
    </div>
    ${framing ? `<div class="callout callout-neutral" style="margin-top:10px;">
        <div style="margin-bottom:6px;">${categoryBadge(category)}</div>${framing}
        ${fa.failure_stage ? `<div class="small-caps" style="margin-top:8px;">Recorded failure stage: <span class="mono">${esc(fa.failure_stage)}</span>${fa.execution_status ? ` &middot; status <span class="mono">${esc(fa.execution_status)}</span>` : ""}</div>` : ""}
      </div>` : ""}
    <p class="small-caps">Not evidence against the repair proposal itself, which was schema-valid and grounded.</p>
  `;
}

function stepReexec(c, r, stages) {
  const fa = r.fix_applicator;
  if (!fa.attempted) return `<div class="empty-note">Re-execution not performed — no fix was applied to test.</div>`;
  if (fa.outcome === "apply_error") return `<div class="empty-note">Re-execution could not be judged — fix application failed before the notebook could be re-run (see Fix Application).</div>`;

  const targeted = r.round === 1 ? c.original_error.error_message : c.round2.new_error.error_message;
  const resolved = fa.same_as_original_error === false;
  const fixed = fa.outcome === "fixed";
  let resultBlock;
  if (fixed) {
    resultBlock = `<div class="callout callout-good"><strong>Notebook executed successfully after repair.</strong></div>`;
  } else {
    resultBlock = `
      <div class="before-after">
        <div class="ba-col"><div class="ba-label">Targeted error (this round)</div><div class="mono">${esc(targeted)}</div></div>
        <div class="ba-arrow">&rarr;</div>
        <div class="ba-col ${resolved ? "ba-new" : "ba-same"}"><div class="ba-label">${resolved ? "After re-execution: different error" : "After re-execution: same error"}</div><div class="mono">${esc(fa.new_error_type)}: ${esc(fa.new_error_message)}</div></div>
      </div>
      ${resolved
        ? `<div class="callout callout-good"><strong>Targeted error resolved.</strong> The notebook ran further and stopped on a <em>different</em> error. Targeted-error resolution is not full notebook recovery.</div>`
        : `<div class="abstain-banner"><strong>Targeted error persists.</strong> The repair did not change the outcome — the identical error is raised again.</div>`}
    `;
  }

  let next = "";
  if (r.round === 1) {
    const trig = r.round2_trigger;
    const nextIdx = stages.findIndex(s => s.key === "new_error");
    if (c.round2) {
      next = `
        <hr class="sep" />
        <div class="callout callout-neutral round2-open-callout">
          <strong>A genuinely new error appeared.</strong> It is reclassified and explained as its own record, and only then is its repair eligibility decided.
          <div style="margin-top:10px;"><button class="btn btn-primary btn-sm" onclick="goToFlat(${nextIdx})">Open Round 2 &rarr;</button></div>
        </div>`;
    } else {
      next = `<hr class="sep" /><div class="callout callout-neutral"><strong>No second round.</strong> ${esc(TRIGGER_REASON_TEXT[trig.reason] || labelize(trig.reason))}</div>`;
    }
  } else {
    next = `<hr class="sep" /><div class="callout callout-neutral"><strong>Hard cap reached.</strong> Two rounds is the maximum. ${fa.new_error_message ? `The error left after Round 2 (<span class="mono">${esc(fa.new_error_message)}</span>) is recorded but is neither reclassified, explained, nor repaired.` : ""}</div>`;
  }
  return resultBlock + next + `
    <details class="raw-json">
      <summary>View raw re-execution JSON</summary>
      <pre>${esc(JSON.stringify(fa, null, 2))}</pre>
    </details>
  `;
}

function stepNewError(c) {
  const ne = c.round2.new_error;
  const r1 = c.rounds[0];
  return `
    <div class="error-banner">${esc(ne.error_type)}: ${esc(ne.error_message)}</div>
    <div class="before-after" style="margin-top:12px;">
      <div class="ba-col"><div class="ba-label">Round-1 targeted error — resolved</div><div class="mono">${esc(c.original_error.error_message)}</div></div>
      <div class="ba-arrow">&rarr;</div>
      <div class="ba-col ba-new"><div class="ba-label">Exposed by Round-1 re-execution</div><div class="mono">${esc(ne.error_message)}</div></div>
    </div>
    ${kvGrid([
      ["Round-1 repair that exposed it", `<code>${esc(r1.fix_applicator.command)}</code>`],
      ["Same as the original error?", boolBadge(false, "Yes", "No — genuinely new")],
      ["What happens next", "Reclassification (which decides repair eligibility) &rarr; new explanation &rarr; repair only if eligible"],
    ])}
    <p class="small-caps">This error was invisible in the original dataset row: execution only reached it after the first dependency error was removed.</p>
  `;
}

function stepFinal(c) {
  const fr = c.final_result;
  const t1 = fr.targeted_error_resolved_round1;
  const t2 = fr.targeted_error_resolved_round2;
  const r2 = c.round2;
  const rows = [
    ["Final notebook classification", categoryBadge(fr.final_category)],
    ["Fully recovered (runs end-to-end)?", boolBadge(fr.final_category === "fixed")],
    ["Round-1 targeted error resolved", boolBadge(t1)],
    ...(r2 && r2.executed ? [["Round-2 targeted error resolved", boolBadge(t2)]] : []),
    ["Repair rounds executed", `<span class="mono">${c.rounds.length} / 2</span>`],
    ["Original failure explained", c.explanation.status === "success" ? badge("Yes", "good") : badge("No — runtime failure", "warn")],
    ...(r2 ? [["Newly exposed error explained", r2.explanation.status === "success" ? badge("Yes", "good") : badge("No — runtime failure", "warn")],
              ["Newly exposed error repaired", r2.repair_status === "attempted" ? badge("Round-2 repair applied", "accent") : r2.repair_status === "abstained" ? badge("Round 2 abstained (mapping unknown)", "warn") : badge("Not eligible — explanation only", "neutral")]] : []),
  ];
  const story = finalStoryText(c);
  return `
    ${kvGrid(rows)}
    <div class="callout ${t1 || t2 ? "callout-good" : "callout-neutral"}" style="margin-top:12px;">${story}</div>
    <p class="small-caps" style="margin-top:8px;">Final classification as recorded in <span class="mono">per_notebook_comparison.csv</span> of the frozen run. Targeted-error resolution and full notebook recovery are different questions and are reported separately.</p>
  `;
}

function finalStoryText(c) {
  const fr = c.final_result;
  const r1 = c.rounds[0];
  const r2 = c.round2;
  if (fr.final_category === "abstained" && !r2) return `The repair agent abstained in Round 1 because the failing import (<span class="mono">${esc(c.original_error.failing_module)}</span>) has no supported PyPI mapping. No fix was applied and the notebook was not re-executed. This is deliberate: the system does not guess an unsupported package name.`;
  if (fr.final_category === "infrastructure_failure") return `A schema-valid, grounded repair was proposed, but the environment could not be rebuilt (${esc(FAILURE_STAGE_TEXT[r1.fix_applicator.failure_stage] || "tooling fault")}). The record is kept separate from method-level results.`;
  if (fr.final_category === "method_failure") return `A schema-valid, grounded repair was proposed, but the application could not be judged (${esc(r1.fix_applicator.diagnostic_message || "recorded diagnostic")}). Because the cause is not unambiguously external, the record stays a method failure.`;
  if (r1.round2_trigger.reason === "same_as_original_error") return `The Round-1 repair (<span class="mono">${esc(r1.fix_applicator.command)}</span>) was applied and the notebook re-executed, but the identical error was raised again. The targeted error was not resolved and no second round applied.`;
  if (r2 && r2.repair_status === "attempted") return `Both repairs did what they were meant to do: each removed the dependency error it targeted. The notebook still stops on a further error (<span class="mono">${esc(c.rounds[1].fix_applicator.new_error_message || "")}</span>) that lies beyond the two-round cap.`;
  if (r2 && r2.repair_status === "abstained") return `The Round-1 repair removed its targeted error. The newly exposed error was reclassified and explained, and was repair-eligible, but its import has no supported PyPI mapping, so Round 2 abstained rather than guess.`;
  if (r2 && r2.trace_only) return `The Round-1 repair removed its targeted error. The newly exposed error (${esc(labelize(r2.record.subtype))}) was explained for the reader but lies outside the pip-only repair scope, so no second repair round was attempted.`;
  return `Recorded final state: ${esc(labelize(fr.final_category))}.`;
}

// ---------------------------------------------------------------------
// Side rail
// ---------------------------------------------------------------------

function storyCardHtml(c, stages) {
  const rows = stages.map((s, i) => {
    const cls = i < wsState.flat ? "seen" : i === wsState.flat ? "active" : "future";
    const mark = i > wsState.flat ? "·" : s.state === "abstained" ? "A" : s.state === "failed" ? "×" : s.state === "skipped" ? "–" : "✓";
    const roundTag = (s.round === 2 && !s.final && (i === 0 || stages[i - 1].round !== 2)) ? '<div class="story-round">Round 2 · newly exposed error</div>' : "";
    let gate = "";
    if (s.key === "explanation" || s.key === "explanation2") {
      const g = eligibilityOf(c, s.round);
      const reached = i < wsState.flat;
      gate = g.eligible
        ? `<div class="story-gate ok ${reached ? "seen" : "future"}"><span class="gate-mark">&#10003;</span> repair-eligible &rarr; repair</div>`
        : `<div class="story-gate stop ${reached ? "seen" : "future"}"><span class="gate-mark">&#10007;</span> not repair-eligible &rarr; stop</div>`;
    }
    return `${roundTag}
      <button class="story-row ${cls} state-${s.state}" data-flat-index="${i}">
        <span class="story-mark">${mark}</span>
        <span class="story-label">${esc(s.label)}</span>
        <span class="story-sub">${esc(storyDetail(c, s))}</span>
      </button>${gate}`;
  }).join("");
  return `
    <div class="card story-card">
      <div class="card-title">This notebook's story</div>
      <div class="story-list">${rows}</div>
    </div>`;
}

function storyDetail(c, s) {
  const r = roundFor(c, s);
  switch (s.key) {
    case "failure": return `${c.original_error.error_type}: ${c.original_error.failing_module}`;
    case "classifier": return `${labelize(r.classifier.subtype)}, ${r.classifier.scope_status}`;
    case "explanation": return c.explanation.status === "success" ? "completed, schema-valid" : `runtime failure (${(c.explanation.failure || {}).category || "failed"})`;
    case "rag": return r.repair_agent.status === "success" ? `${labelize(r.repair_agent.action)} ${r.repair_agent.install_name}${r.repair_agent.version ? "==" + r.repair_agent.version : ""}` : "abstained (mapping unknown)";
    case "fix": return r.fix_applicator.attempted ? (r.fix_applicator.outcome === "apply_error" ? `failed: ${r.fix_applicator.failure_stage}` : "applied in rebuilt container") : "skipped";
    case "reexec": return r.fix_applicator.attempted ? (r.fix_applicator.outcome === "apply_error" ? "not judged" : r.fix_applicator.same_as_original_error === false ? "targeted error resolved, new error" : "same error persists") : "skipped";
    case "new_error": return `${c.round2.new_error.error_type}: ${c.round2.record.failing_module || c.round2.new_error.error_message}`;
    case "reclassify": return `${labelize(c.round2.record.subtype)}, ${c.round2.record.scope_status}`;
    case "explanation2": return c.round2.explanation.status === "success" ? "completed, schema-valid" : "runtime failure";
    case "final": return labelize(c.final_result.final_category);
    default: return "";
  }
}

function finalResultCardHtml(c) {
  const fr = c.final_result;
  const t1 = fr.targeted_error_resolved_round1;
  const t2 = fr.targeted_error_resolved_round2;
  return `
    <div class="card final-result-card">
      <div class="card-title">Final Result</div>
      <div class="row"><span class="lbl">Final notebook state</span>${categoryBadge(fr.final_category)}</div>
      <div class="row"><span class="lbl">Targeted error resolved (R1)</span>${boolBadge(t1)}</div>
      ${c.round2 && c.round2.executed ? `<div class="row"><span class="lbl">Targeted error resolved (R2)</span>${boolBadge(t2)}</div>` : ""}
      <div class="row"><span class="lbl">Rounds executed</span><span class="mono">${c.rounds.length} / 2</span></div>
      ${c.round2 ? `<div class="row"><span class="lbl">New error explained</span>${c.round2.explanation.status === "success" ? badge("Yes", "good") : badge("No", "warn")}</div>
                    <div class="row"><span class="lbl">New error repair-eligible</span>${boolBadge(c.round2.eligible)}</div>` : ""}
      <div class="row"><span class="lbl">Notebook fully fixed?</span>${boolBadge(fr.final_category === "fixed")}</div>
    </div>
    ${fr.final_category !== "fixed" && (t1 || t2) ? `
      <div class="callout callout-good" style="font-size:12.5px;">
        The individual repair(s) worked as designed — the targeted dependency error(s) were resolved. The
        notebook still does not run end-to-end because a <em>different, later</em> error remains.
      </div>` : ""}
  `;
}
