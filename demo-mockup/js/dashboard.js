/* Overview: final Gemma-2 9B results (run i10), the pipeline with its bounded
   second round, and real showcase notebooks to open. All numbers are copied
   from the frozen run's summary files by build_demo_data.py. */

function renderDashboard() {
  const g = EVALUATION.gemma;
  const ex = g.explanation;
  const rp = g.repair;
  const ds = EVALUATION.dataset;
  const n = rp.evaluation_notebooks;
  const fo = rp.final_outcomes;
  const order = [164, 158, 163, 79, 134, 21, 203, 189, 445, 370];
  const showcase = CASES.filter(c => c.showcase).sort((a, b) => order.indexOf(a.notebook_execution_id) - order.indexOf(b.notebook_execution_id));

  const html = `
    <div class="page-header">
      <h1 class="page-title">Dependency Failure Explanation &amp; Repair Pipeline</h1>
      <p class="page-sub">Open-LLM-based explanation and PyPI-grounded repair of dependency-related Jupyter Notebook failures, with a bounded second round for errors that a first repair exposes.</p>
      <span class="recorded-run-badge"><span class="dot"></span> Recorded run &middot; ${esc(g.model_label)} &middot; <span class="mono">${esc(g.run_id)}</span></span>
    </div>

    <div class="grid grid-4">
      ${miniStat(n, "Evaluation notebooks", `${ds.total_rows} dependency-error records &middot; ${ds.scope_status_counts.usable} pip-repairable &middot; ${ds.split_counts.dev} dev / ${n} evaluation`)}
      ${miniStat(`${ex.combined.completed}/${ex.combined.records}`, "Explanations completed", `${ex.original.completed}/${ex.original.records} original failures + ${ex.round2.completed}/${ex.round2.records} newly exposed errors`)}
      ${miniStat(`${rp.targeted_resolved_total}/${rp.repair_llm_responses}`, "Targeted errors resolved", `${fmtPct(rp.targeted_resolution_rate)} of the ${rp.repair_llm_responses} real repair attempts removed the error they targeted`)}
      ${miniStat(`${fo.fixed}/${n}`, "Fully recovered notebooks", "No notebook ran end-to-end within two rounds — a different, later error remained (see below)")}
    </div>

    <div class="card callout callout-good" style="margin-top:16px;">
      <strong>Read these together.</strong> A targeted error being resolved means the specific dependency error a repair addressed is gone
      after re-execution. Full notebook recovery means the notebook runs top-to-bottom with no error. ${rp.targeted_resolved_total} of ${rp.repair_llm_responses}
      real repairs achieved the first; ${fo.fixed} of ${n} notebooks achieved the second, because most notebooks fail on more than one
      dependency in turn and because the repair agent abstains whenever it cannot ground a package name.
    </div>

    <div class="card" style="margin-top:16px;">
      <div class="card-title">Pipeline &middot; two rounds maximum</div>
      ${pipelineDiagramHtml()}
    </div>

    <div class="grid grid-2" style="margin-top:16px;">
      <div class="card">
        <div class="card-title">Explanation &middot; completion and schema validity</div>
        ${explanationRows(ex)}
        <p class="footer-note" style="margin-top:10px;">Completion: the model returned a response that could be processed within one retry. The
        ${ex.original.runtime_failures} missing original explanations are <strong>runtime failures</strong>
        (${Object.entries(ex.original.runtime_failure_categories).map(([k, v]) => `${v} ${labelize(k).toLowerCase()}`).join(", ")}) of the local
        Ollama service: no response arrived, so there was nothing to validate. Every response that did arrive was schema-valid.</p>
      </div>
      <div class="card">
        <div class="card-title">Repair &middot; ${n} notebooks, ${rp.repair_agent_invocations} repair-agent invocations</div>
        ${kvGrid([
          ["Round-1 abstentions", `${rp.round1_abstentions} / ${n} &middot; ${fmtPct(rp.round1_abstention_rate)}`],
          ["Final-state abstentions", `${rp.final_state_abstentions} / ${n} &middot; ${fmtPct(rp.final_state_abstention_rate)}`],
          ["Real repair-LLM responses", `${rp.repair_llm_responses} (${rp.repair_llm_responses_round1} R1 + ${rp.repair_llm_responses_round2} R2)`],
          ["Schema-valid / grounded", `${rp.repair_llm_responses}/${rp.repair_llm_responses} &middot; ${rp.repair_llm_responses}/${rp.repair_llm_responses}`],
          ["Targeted errors resolved", `${rp.targeted_resolved_total} / ${rp.repair_llm_responses} (${rp.targeted_resolved_round1}/${rp.repair_llm_responses_round1} R1, ${rp.targeted_resolved_round2}/${rp.repair_llm_responses_round2} R2)`],
          ["Full notebook recovery", `${fo.fixed} / ${n}`],
        ])}
      </div>
    </div>

    <div class="card" style="margin-top:16px;">
      <div class="card-title">Final outcomes of the ${n} evaluation notebooks</div>
      <div class="outcome-bar">
        ${outcomeSeg("abstained", fo.abstained, n)}
        ${outcomeSeg("still_failing", fo.still_failing, n)}
        ${outcomeSeg("infrastructure_failure", fo.infrastructure_failure, n)}
        ${outcomeSeg("method_failure", fo.method_failure, n)}
      </div>
      <div class="outcome-legend">
        ${outcomeLegend("abstained", fo.abstained, "no grounded package candidate; nothing applied")}
        ${outcomeLegend("still_failing", fo.still_failing, "repair applied; a later error remains")}
        ${outcomeLegend("infrastructure_failure", fo.infrastructure_failure, "environment fault, no fair trial")}
        ${outcomeLegend("method_failure", fo.method_failure, "not judgeable, cause not clearly external")}
        ${outcomeLegend("fixed", fo.fixed, "runs end-to-end")}
      </div>
      <p class="footer-note" style="margin-top:8px;">Round 2: ${rp.round2_eligible} notebooks were eligible for a second repair, ${rp.round2_proposals} received a grounded Round-2 proposal (all applied), ${rp.round2_abstained} abstained again on an unmapped import. ${ex.round2.explained_not_repair_eligible_trace_only} further newly exposed errors were explained but were outside repair scope.</p>
    </div>

    <div class="card" style="margin-top:16px;">
      <div class="card-title">Showcase notebooks &middot; real records from the final run</div>
      <p class="page-sub" style="margin-top:-4px;">Each opens the Repair Workspace for that notebook's recorded trace.</p>
      <div class="case-picker">
        ${showcase.map(caseCard).join("")}
      </div>
      <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btn" onclick="navigate('#/notebooks')">Browse all ${n} notebooks &rarr;</button>
        <button class="btn" onclick="navigate('#/evaluation')">Evaluation summary &rarr;</button>
        <button class="btn" onclick="navigate('#/comparison')">Gemma vs Qwen &rarr;</button>
      </div>
    </div>
  `;
  document.getElementById("main").innerHTML = html;
}

function miniStat(value, label, note) {
  return `
    <div class="stat-card">
      <div class="stat-value">${esc(value)}</div>
      <div class="stat-label">${esc(label)}</div>
      ${note ? `<div class="stat-note">${note}</div>` : ""}
    </div>`;
}

function explanationRows(ex) {
  const row = (label, o) => `
    <tr>
      <td>${label}</td>
      <td class="mono">${o.completed}/${o.records}</td>
      <td class="mono">${fmtPct(o.completion_rate)}</td>
      <td class="mono">${o.runtime_failures}</td>
      <td class="mono">${o.completed}/${o.completed}</td>
    </tr>`;
  return `
    <div style="overflow-x:auto;">
    <table class="data-table compact">
      <thead><tr><th>Population</th><th>Completed</th><th>Rate</th><th>Runtime failures</th><th>Schema-valid among completed</th></tr></thead>
      <tbody>
        ${row("Original failures", ex.original)}
        ${row("Newly exposed (Round 2)", ex.round2)}
        ${row("Combined", ex.combined)}
      </tbody>
    </table>
    </div>`;
}

function outcomeSeg(cat, count, total) {
  if (!count) return "";
  const kind = CATEGORY_BADGE[cat] || "neutral";
  return `<div class="outcome-seg seg-${kind}" style="flex:${count};" title="${esc(labelize(cat))}: ${count}"><span>${count}</span></div>`;
}
function outcomeLegend(cat, count, note) {
  return `<div class="outcome-legend-item">${categoryBadge(cat)}<span class="mono">${count}</span><span class="outcome-note">${esc(note)}</span></div>`;
}

function pipelineDiagramHtml() {
  return `
    <div class="pipe-diagram">
      <div class="pipe-row">
        <div class="pipe-row-label">Round 1</div>
        ${pipeNode("Original failure", "recorded by the Docker pipeline")}
        ${pipeArrow()}
        ${pipeNode("ErrorClassifier", "subtype · repair scope")}
        ${pipeArrow()}
        ${pipeNode("LLMExplainer", "plain-language explanation")}
        ${pipeArrow()}
        ${pipeGate()}
        ${pipeArrow()}
        ${pipeNode("RAGRepairAgent", "PyPI-grounded proposal")}
        ${pipeArrow()}
        ${pipeNode("FixApplicator", "rebuilt Docker env")}
        ${pipeArrow()}
        ${pipeNode("Re-execution", "top-to-bottom")}
      </div>
      <div class="pipe-loop-note">&#8617; if re-execution exposes a <strong>genuinely new</strong> error (never a direct FixApplicator &rarr; RAGRepairAgent feedback)</div>
      <div class="pipe-row pipe-row-r2">
        <div class="pipe-row-label r2">Round 2</div>
        ${pipeNode("New error", "from Round-1 re-execution")}
        ${pipeArrow()}
        ${pipeNode("Reclassification", "same two classifier stages")}
        ${pipeArrow()}
        ${pipeNode("Round-2 LLMExplainer", "explains the new error")}
        ${pipeArrow()}
        ${pipeGate()}
        ${pipeArrow()}
        ${pipeNode("RAGRepairAgent", "only if eligible")}
        ${pipeArrow()}
        ${pipeNode("FixApplicator + re-run", "R1 fix replayed + R2 fix")}
        ${pipeArrow()}
        ${pipeNode("Final result", "hard cap: no Round 3", "final")}
      </div>
    </div>
    <p class="footer-note" style="margin-top:8px;">The repair-eligibility gate is not a component: it is the orchestrator's decision derived from the classifier's subtype and scope. Explanation is independent of repair in both rounds: the repair agent never receives the explanation, and a failed explanation does not block an eligible repair. A newly exposed error outside the pip-only scope is explained, then the second round stops.</p>
  `;
}

function pipeNode(label, sub, kind) {
  return `<div class="pipe-node ${kind || ""}"><div class="pn-label">${esc(label)}</div><div class="pn-sub">${esc(sub)}</div></div>`;
}
function pipeArrow() {
  return `<div class="pipe-arrow">&rarr;</div>`;
}
function pipeGate() {
  return `<div class="pipe-gate" title="Orchestrator decision derived from the classification (subtype + scope)"><span class="gate-mark">?</span>repair-<br/>eligible?</div>`;
}

function caseCard(c) {
  const fr = c.final_result;
  return `
    <div class="case-pick-card" onclick="navigate('#/workspace/${c.id}')">
      <div class="cp-label">Notebook #${c.notebook_execution_id} &middot; ${esc(repoShortName(c.repository_url))}</div>
      <div class="cp-title">${esc(c.original_error.error_type)}: ${esc(c.original_error.failing_module)}</div>
      <div class="cp-desc">${esc(c.showcase)}</div>
      <div class="cp-badges">${categoryBadge(fr.final_category)}${c.round2 ? (c.round2.repair_status === "attempted" ? badge("Round 2 repaired", "r2") : c.round2.repair_status === "abstained" ? badge("Round 2 abstained", "warn") : badge("Round 2 explained only", "neutral")) : ""}</div>
    </div>`;
}
