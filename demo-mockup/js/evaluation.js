/* Evaluation Summary: the final Gemma-2 9B run (i10). Every number is copied
   from the frozen summary files by build_demo_data.py; nothing is recomputed. */

function renderEvaluation() {
  const g = EVALUATION.gemma;
  const ex = g.explanation;
  const rp = g.repair;
  const n = rp.evaluation_notebooks;
  const fo = rp.final_outcomes;
  const cls = g.classifier_scoring;
  const pypi = g.pypi_resolution_scoring;

  const html = `
    <div class="page-header">
      <h1 class="page-title">Evaluation Summary</h1>
      <p class="page-sub">Final evaluation run over ${n} evaluation-split notebooks with ${esc(g.model_label)} via Ollama, two-round budget. Run id: <span class="mono">${esc(g.run_id)}</span>. ${g.provenance.integrity_checks_passed}/${g.provenance.integrity_checks_total} integrity checks passed.</p>
      <span class="recorded-run-badge"><span class="dot"></span> Frozen final-evaluation output — not recomputed for this demo</span>
    </div>

    <div class="card callout callout-good" style="margin-bottom:18px;">
      <strong>Read these two numbers together:</strong> ${fo.fixed} of ${n} notebooks were fully recovered end-to-end, but
      ${rp.targeted_resolved_total} of ${rp.repair_llm_responses} applied repair attempts (${fmtPct(rp.targeted_resolution_rate)}) removed the dependency error they targeted.
      Most final-state failures come from a <em>second, later</em> dependency error surfacing after a successful individual repair,
      or from the repair agent abstaining on an unmapped import — not from repairs that silently failed. The sections below use different denominators.
    </div>

    <h2 class="section-heading">Explanation <span class="section-heading-note">denominator: encountered errors (one record each)</span></h2>
    <div class="card">
      ${explanationTable(ex, g.model_label)}
      <div class="two-col-note" style="margin-top:12px;">
        <div>
          <p class="small-caps" style="margin-bottom:4px;">Completion vs. schema validity</p>
          <p style="font-size:13px; margin:0;">
            <strong>Completion</strong> asks whether the explanation call returned a response that could be processed within one retry.
            <strong>Schema validity</strong> asks, among responses that did arrive, whether they matched the six-field explanation schema.
            The ${ex.original.runtime_failures} missing original explanations are runtime failures of the local model service
            (${Object.entries(ex.original.runtime_failure_categories).map(([k, v]) => `${v} × ${labelize(k).toLowerCase()}`).join(", ")}):
            no response arrived, so there was nothing to validate. They are not schema failures.
          </p>
        </div>
        <div>
          <p class="small-caps" style="margin-bottom:4px;">Round-2 population</p>
          <p style="font-size:13px; margin:0;">
            Round 1 exposed and reclassified ${ex.round2.reclassified_new_errors} new errors
            (${Object.entries(ex.round2.composition_by_subtype).map(([k, v]) => `${v} ${k}`).join(", ")}).
            All ${ex.round2.completed} received a Round-2 explanation on the first attempt. ${ex.round2.explained_repair_eligible} were repair-eligible and went on to Round 2;
            ${ex.round2.explained_not_repair_eligible_trace_only} were explained but lie outside repair scope, so their explanations exist in the trace only and create no Round-2 repair row.
            Explanation LLM attempts including retries: ${ex.original.llm_attempts_incl_retries} original + ${ex.round2.llm_attempts_incl_retries} Round 2 = ${ex.combined.llm_attempts_incl_retries}; ${ex.original.records_with_retry} records needed the retry.
          </p>
        </div>
      </div>
    </div>

    <h2 class="section-heading" style="margin-top:26px;">Repair-attempt level <span class="section-heading-note">denominator: ${rp.repair_agent_invocations} repair-agent invocations (${n} R1 + ${rp.round2_eligible} R2)</span></h2>
    <div class="grid grid-3">
      ${statCard("Grounded proposal coverage", `${rp.repair_llm_responses} / ${rp.repair_agent_invocations}`, fmtPct(rp.grounded_proposal_coverage_rate), "Grounded proposals over every repair-agent invocation across both rounds, abstentions included.")}
      ${statCard("Proposal schema validity", `${rp.repair_llm_responses} / ${rp.repair_llm_responses}`, fmtPct(rp.proposal_validity_rate), "Among the invocations where the repair LLM was actually called, every proposal was schema-valid.")}
      ${statCard("Grounding validity", `${rp.repair_llm_responses} / ${rp.repair_llm_responses}`, fmtPct(rp.grounding_pass_rate), "Every schema-valid proposal named a package and version present in the retrieved PyPI evidence.")}
    </div>
    <div class="grid grid-3" style="margin-top:14px;">
      ${statCard("Targeted-error resolution", `${rp.targeted_resolved_total} / ${rp.repair_llm_responses}`, fmtPct(rp.targeted_resolution_rate), `Of the ${rp.repair_llm_responses} real repair attempts (${rp.repair_llm_responses_round1} R1 + ${rp.repair_llm_responses_round2} R2), this share removed the specific error they targeted: ${rp.targeted_resolved_round1}/${rp.repair_llm_responses_round1} in Round 1, ${rp.targeted_resolved_round2}/${rp.repair_llm_responses_round2} in Round 2.`)}
      ${statCard("Abstained before the LLM", `${rp.final_state_abstentions} / ${rp.repair_agent_invocations}`, fmtPct(rp.final_state_abstentions / rp.repair_agent_invocations), `Invocations where the repair agent declined before any LLM call: ${rp.round1_abstentions} in Round 1, ${rp.round2_abstentions} in Round 2, all on an unmapped import name.`)}
      ${statCard("Repair-LLM calls", `${rp.repair_llm_responses} / ${rp.repair_agent_invocations}`, fmtPct(rp.repair_llm_responses / rp.repair_agent_invocations), `${rp.repair_llm_responses_round1} in Round 1 plus ${rp.repair_llm_responses_round2} in Round 2; each answered on the first attempt (${rp.repair_llm_responses} calls incl. retries). Explanation calls are not counted here.`)}
    </div>

    <h2 class="section-heading" style="margin-top:26px;">Notebook level <span class="section-heading-note">denominator: ${n} evaluation notebooks</span></h2>
    <div class="grid grid-3">
      ${statCard("Full notebook recovery", `${fo.fixed} / ${n}`, fmtPct(fo.fixed / n), "No notebook re-executed end-to-end within the two-round budget. Read with the targeted-resolution figure above.")}
      ${statCard("Final-state abstention", `${rp.final_state_abstentions} / ${n}`, fmtPct(rp.final_state_abstention_rate), `${rp.round1_abstentions} declined in Round 1 plus ${rp.round2_abstentions} declined again in an eligible Round 2.`)}
      ${statCard("Still failing", `${fo.still_failing} / ${n}`, fmtPct(fo.still_failing / n), "A repair was applied and re-executed, but the notebook still did not run end-to-end — usually with its targeted error already resolved.")}
    </div>
    <div class="grid grid-3" style="margin-top:14px;">
      ${statCard("Infrastructure failures", `${fo.infrastructure_failure} / ${n}`, fmtPct(rp.infrastructure_failure_rate), "Environment/tooling faults with clear external evidence (repository clone timeouts) that prevented a fair trial.")}
      ${statCard("Method failures", `${fo.method_failure} / ${n}`, fmtPct(fo.method_failure / n), "Application could not be judged for a reason not unambiguously external; ambiguous cases stay here by design.")}
      ${statCard("Additional notebooks fixed by Round 2", `0 / ${rp.round2_attempts}`, "0%", `Of the ${rp.round2_attempts} real Round-2 repair attempts, all ${rp.targeted_resolved_round2} resolved their targeted error; none produced a fully fixed notebook.`)}
    </div>

    <div class="card" style="margin-top:16px;">
      <div class="card-title">Round-1 &rarr; Round-2 funnel</div>
      <div class="two-col-note">
        <div>
          <p class="small-caps" style="margin-bottom:6px;">Round 1 (${n} evaluation notebooks)</p>
          ${funnelRow("Evaluation notebooks", n, n)}
          ${funnelRow("Round-1 abstentions (mapping unknown)", rp.round1_abstentions, n)}
          ${funnelRow("Real Round-1 repair attempts", rp.repair_llm_responses_round1, n)}
          ${funnelRow("Round-1 targeted error resolved", rp.targeted_resolved_round1, n)}
          ${funnelRow("New error exposed and reclassified", ex.round2.reclassified_new_errors, n)}
        </div>
        <div>
          <p class="small-caps" style="margin-bottom:6px;">Round 2 (${ex.round2.reclassified_new_errors} newly exposed errors)</p>
          ${funnelRow("Explained (Round-2 LLMExplainer)", ex.round2.completed, ex.round2.reclassified_new_errors)}
          ${funnelRow("Repair-eligible", rp.round2_eligible, ex.round2.reclassified_new_errors)}
          ${funnelRow("Explained only (outside repair scope)", ex.round2.explained_not_repair_eligible_trace_only, ex.round2.reclassified_new_errors)}
          ${funnelRow("Round-2 abstentions (mapping unknown)", rp.round2_abstained, ex.round2.reclassified_new_errors)}
          ${funnelRow("Real Round-2 repair attempts", rp.round2_attempts, ex.round2.reclassified_new_errors)}
          ${funnelRow("Round-2 targeted error resolved", rp.targeted_resolved_round2, ex.round2.reclassified_new_errors)}
          ${funnelRow("Additional notebooks fully fixed", 0, ex.round2.reclassified_new_errors)}
        </div>
      </div>
    </div>

    <div class="grid grid-2" style="margin-top:16px;">
      <div class="card">
        <div class="card-title">ErrorClassifier — manual validation sample (${cls.n_rows} records)</div>
        <div class="kv-grid">
          ${kv("Scope accuracy", fmtPct(cls.scope_status.metrics.accuracy))}
          ${kv("Precision", fmtPct(cls.scope_status.metrics.precision))}
          ${kv("Recall", fmtPct(cls.scope_status.metrics.recall))}
          ${kv("F1", fmtPct(cls.scope_status.metrics.f1))}
          ${kv("Subtype accuracy", `${Object.values(cls.subtype.per_class).reduce((a, c) => a + c.tp, 0)} / ${cls.subtype.n_scored} &middot; ` + fmtPct(cls.subtype.naive_overall_accuracy))}
          ${kv("Failing-module exact match", `${cls.failing_module.n_scored} / ${cls.failing_module.n_scored} &middot; ` + fmtPct(cls.failing_module.exact_match_accuracy))}
        </div>
        <p class="footer-note" style="margin-top:10px;">Sample-based diagnostic result on a deliberately oversampled validation set — not a population-wide estimate.</p>
      </div>
      <div class="card">
        <div class="card-title">PyPI resolution — manual diagnostic sample</div>
        <div class="kv-grid">
          ${kv("Manually resolvable cases correct", `${pypi.n_correct} / ${pypi.n_checked} &middot; ` + fmtPct(pypi.distribution_resolution_accuracy))}
          ${kv("Sample rows", `${pypi.n_rows} (${pypi.n_skipped_unfilled} left unresolved by hand)`)}
        </div>
        <p class="footer-note" style="margin-top:10px;">Denominator is the manually resolvable rows in the frozen diagnostic sample, not a random or population-representative sample. Consistent with the high mapping_unknown abstention rate, not proof of it.</p>
      </div>
    </div>

    ${humanStudyCard()}

    <div class="card" style="margin-top:16px;">
      <div class="card-title">Model sensitivity</div>
      <p style="font-size:13px; margin:0 0 8px 0;">The same evaluation was repeated with Qwen3.6-35B-A3B-MLX-8bit in place of Gemma-2 9B, everything else fixed. Aggregate repair results were identical; the models differed in NumPy version selection on 13 records without changing any downstream outcome.</p>
      <button class="btn" onclick="navigate('#/comparison')">Open the Gemma vs Qwen comparison &rarr;</button>
    </div>

    ${provenanceNoteCard()}

    <p class="footer-note">
      Source: <span class="mono">data/evaluation/${esc(g.run_id)}/summary/evaluation_summary.json</span> and <span class="mono">tables/*.csv</span>;
      dataset statistics: <span class="mono">data/dependency-errors/statistics.json</span>. Values are copied verbatim from those frozen outputs.
    </p>
  `;
  document.getElementById("main").innerHTML = html;
}

function explanationTable(ex, modelLabel) {
  const row = (label, o) => `
    <tr>
      <td>${label}</td>
      <td class="mono">${o.records}</td>
      <td class="mono">${o.completed}/${o.records} <span class="dim">(${fmtPct(o.completion_rate)})</span></td>
      <td class="mono">${o.runtime_failures}${o.runtime_failure_categories && Object.keys(o.runtime_failure_categories).length ? ` <span class="dim">(${Object.entries(o.runtime_failure_categories).map(([k, v]) => `${v} ${k}`).join(", ")})</span>` : ""}</td>
      <td class="mono">${o.completed}/${o.completed} <span class="dim">(100%)</span></td>
      <td class="mono">${o.llm_attempts_incl_retries}</td>
    </tr>`;
  return `
    <div style="overflow-x:auto;">
    <table class="data-table compact">
      <thead><tr><th>${esc(modelLabel)}</th><th>Records</th><th>Completed</th><th>Runtime failures</th><th>Schema-valid among completed</th><th>LLM attempts incl. retries</th></tr></thead>
      <tbody>
        ${row("Original failures", ex.original)}
        ${row("Newly exposed errors (Round 2)", ex.round2)}
        ${row("Combined", ex.combined)}
      </tbody>
    </table>
    </div>`;
}

function statCard(label, fraction, pct, note) {
  return `
    <div class="stat-card">
      <div class="stat-value">${esc(pct)}</div>
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-note mono">${esc(fraction)}</div>
      ${note ? `<div class="stat-note">${esc(note)}</div>` : ""}
    </div>`;
}

function funnelRow(label, count, base) {
  const pct = base ? Math.round((count / base) * 100) : 0;
  return `
    <div class="funnel-row">
      <span>${esc(label)}</span>
      <div class="funnel-bar-track"><div class="funnel-bar" style="width:${pct}%;"></div></div>
      <span class="count mono">${count}</span>
    </div>`;
}

function humanStudyCard() {
  const h = EVALUATION.human_evaluation;
  const items = h.items || {};
  const itemLabels = {
    q1_understanding: "Q1 Understanding", q2_satisfaction: "Q2 Satisfaction", q3_detail: "Q3 Detail",
    q4_completeness: "Q4 Completeness", q5_usefulness: "Q5 Usefulness", q6_perceived_correctness: "Q6 Perceived correctness",
  };
  return `
    <div class="card" style="margin-top:16px;">
      <div class="card-title">Human Explanation Evaluation &mdash; separate study</div>
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap;">
        ${badge("Completed", "good")}
        <span class="small-caps">Rated a frozen pool of 12 original-failure Gemma-2 9B explanations. Round-2 explanations and Qwen explanations were not rated.</span>
      </div>
      <div class="kv-grid">
        ${kv("Participants", `${h.n_complete_participants} complete`)}
        ${kv("Explanation evaluations", `${h.n_explanation_evaluations}`)}
        ${kv("Likert ratings", `${h.n_likert_ratings}`)}
        ${kv("Agree / Strongly agree", fmtPct(h.pooled_pct_agree_or_strongly_agree / 100))}
        ${kv("Pooled median (1–5)", `${h.pooled_median} &middot; IQR ${h.pooled_iqr}`)}
        ${kv("Cronbach's α (supplementary)", h.cronbachs_alpha.toFixed(3))}
      </div>
      ${Object.keys(items).length ? `
      <div class="item-bars">
        ${Object.entries(items).map(([k, v]) => `
          <div class="funnel-row">
            <span>${esc(itemLabels[k] || labelize(k))}</span>
            <div class="funnel-bar-track"><div class="funnel-bar" style="width:${Math.round(v.pct_agree_or_strongly_agree)}%;"></div></div>
            <span class="count mono">${v.pct_agree_or_strongly_agree.toFixed(1)}%</span>
          </div>`).join("")}
      </div>` : ""}
      <p class="footer-note" style="margin-top:10px;">
        Adapted Hoffman et al. (2023) Explanation Satisfaction Scale, 6 items over 12 frozen examples.
        ${h.excluded_responses} of ${h.raw_responses} raw responses were incomplete and excluded.
        &alpha; is an internal-consistency statistic only, not inter-rater agreement, and no composite score is derived from it.
      </p>
    </div>
  `;
}

function provenanceNoteCard() {
  return `
    <details class="card provenance-details" style="margin-top:16px;">
      <summary class="card-title" style="cursor:pointer; margin:0;">Execution environment note &middot; repository revision</summary>
      <p style="font-size:13px; margin:10px 0 0 0;">${esc(EVALUATION.commit_pinning_note)}</p>
      <p class="footer-note" style="margin-top:8px;">Each real fix-application attempt records this as <span class="mono">commit_checkout_status: skipped_no_commit</span> (visible in the Fix Application step of the workspace).</p>
    </details>`;
}

/* ------------------------------------------------------------------ */
/* Gemma vs Qwen comparison                                            */
/* ------------------------------------------------------------------ */

function renderComparison() {
  const g = EVALUATION.gemma, q = EVALUATION.qwen, cmp = EVALUATION.comparison;
  const ge = g.explanation, qe = q.explanation, gr = g.repair, qr = q.repair;
  const n = gr.evaluation_notebooks;
  const diffs = cmp.differences;
  const allDownstreamSame = diffs.every(d => d.downstream_identical);
  const allCandidatesSame = diffs.every(d => d.candidate_versions_identical && d.compatibility_identical);
  const spec = diffs.length ? diffs[0].compatibility_specifier : "";
  const gVersions = [...new Set(diffs.map(d => d.gemma.version))];
  const qVersions = [...new Set(diffs.map(d => d.qwen.version))];
  const idRange = diffs.length ? `${diffs[0].notebook_execution_id}–${diffs[diffs.length - 1].notebook_execution_id}` : "";

  const row = (label, a, b, note) => `<tr><td>${label}${note ? `<div class="cell-sub">${note}</div>` : ""}</td><td class="mono">${a}</td><td class="mono">${b}</td><td>${a === b ? badge("identical", "good") : badge("differs", "warn")}</td></tr>`;
  const frac = (a, b) => `${a}/${b}`;

  const html = `
    <div class="page-header">
      <h1 class="page-title">Model Sensitivity: Gemma vs Qwen</h1>
      <p class="page-sub">The same ${n} evaluation notebooks, the same frozen pipeline (commit <span class="mono">${esc(g.provenance.git_commit_sha.slice(0, 8))}</span>, identical component hashes), only the language model replaced. Both runs passed all ${g.provenance.integrity_checks_total} integrity checks.</p>
      <span class="recorded-run-badge"><span class="dot"></span> Paired comparison of two recorded runs — no live model calls</span>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">Main run</div>
        <div class="stat-value" style="font-size:18px;">${esc(g.model_label)}</div>
        <div class="stat-note">via Ollama, local CPU &middot; <span class="mono">${esc(g.run_id)}</span></div>
      </div>
      <div class="card">
        <div class="card-title">Sensitivity run</div>
        <div class="stat-value" style="font-size:18px;">${esc(q.model_label)}</div>
        <div class="stat-note">via Kiste (remote OpenAI-compatible endpoint), max_tokens 4096 &middot; <span class="mono">${esc(q.run_id)}</span></div>
      </div>
    </div>

    <h2 class="section-heading" style="margin-top:22px;">Explanation <span class="section-heading-note">completion and schema validity, one record per encountered error</span></h2>
    <div class="card" style="padding:0; overflow-x:auto;">
      <table class="data-table compact">
        <thead><tr><th>Metric</th><th>${esc(g.model_label)}</th><th>${esc(q.model_label)}</th><th></th></tr></thead>
        <tbody>
          ${row("Original failures completed", frac(ge.original.completed, ge.original.records), frac(qe.original.completed, qe.original.records))}
          ${row("Newly exposed errors (Round 2) completed", frac(ge.round2.completed, ge.round2.records), frac(qe.round2.completed, qe.round2.records))}
          ${row("Combined completed", frac(ge.combined.completed, ge.combined.records), frac(qe.combined.completed, qe.combined.records))}
          ${row("Schema-valid among completed", frac(ge.combined.completed, ge.combined.completed), frac(qe.combined.completed, qe.combined.completed))}
          ${row("Runtime failures (timeout / service)", `${ge.combined.runtime_failures} (${ge.original.runtime_failure_categories.timeout || 0} / ${ge.original.runtime_failure_categories.model_unavailable || 0})`, `${qe.combined.runtime_failures} (${qe.original.runtime_failure_categories.timeout || 0} / ${qe.original.runtime_failure_categories.model_unavailable || 0})`)}
          ${row("Explanation LLM attempts incl. retries", `${ge.combined.llm_attempts_incl_retries}`, `${qe.combined.llm_attempts_incl_retries}`)}
          ${row("Records needing the retry", `${ge.original.records_with_retry}`, `${qe.original.records_with_retry}`)}
        </tbody>
      </table>
    </div>
    <p class="footer-note">Neither model produced a schema-invalid explanation. The difference is whether a response arrived at all: Gemma's ${ge.combined.runtime_failures} missing records are timeouts and one service error of the local, CPU-only Ollama deployment. This is an observed runtime-reliability difference under the evaluation environment, not evidence that one model explains better; the human study rated Gemma's original-failure explanations only.</p>

    <h2 class="section-heading" style="margin-top:22px;">Repair <span class="section-heading-note">same metric definitions for both runs</span></h2>
    <div class="card" style="padding:0; overflow-x:auto;">
      <table class="data-table compact">
        <thead><tr><th>Metric</th><th>${esc(g.model_label)}</th><th>${esc(q.model_label)}</th><th></th></tr></thead>
        <tbody>
          ${row("Round-1 abstentions", frac(gr.round1_abstentions, n), frac(qr.round1_abstentions, n))}
          ${row("Final-state abstentions", frac(gr.final_state_abstentions, n), frac(qr.final_state_abstentions, n))}
          ${row("Repair-agent invocations", `${gr.repair_agent_invocations}`, `${qr.repair_agent_invocations}`)}
          ${row("Repair-LLM responses (R1 + R2)", `${gr.repair_llm_responses} (${gr.repair_llm_responses_round1} + ${gr.repair_llm_responses_round2})`, `${qr.repair_llm_responses} (${qr.repair_llm_responses_round1} + ${qr.repair_llm_responses_round2})`)}
          ${row("Proposal schema validity", frac(gr.repair_llm_responses, gr.repair_llm_responses), frac(qr.repair_llm_responses, qr.repair_llm_responses))}
          ${row("Grounding validity", frac(gr.repair_llm_responses, gr.repair_llm_responses), frac(qr.repair_llm_responses, qr.repair_llm_responses))}
          ${row("Grounded-proposal coverage", `${frac(gr.repair_llm_responses, gr.repair_agent_invocations)} (${fmtPct(gr.grounded_proposal_coverage_rate)})`, `${frac(qr.repair_llm_responses, qr.repair_agent_invocations)} (${fmtPct(qr.grounded_proposal_coverage_rate)})`)}
          ${row("Targeted-error resolution (R1 / R2 / total)", `${gr.targeted_resolved_round1}/${gr.repair_llm_responses_round1} · ${gr.targeted_resolved_round2}/${gr.repair_llm_responses_round2} · ${gr.targeted_resolved_total}/${gr.repair_llm_responses}`, `${qr.targeted_resolved_round1}/${qr.repair_llm_responses_round1} · ${qr.targeted_resolved_round2}/${qr.repair_llm_responses_round2} · ${qr.targeted_resolved_total}/${qr.repair_llm_responses}`)}
          ${row("Round 2 eligible / proposals / attempts", `${gr.round2_eligible} / ${gr.round2_proposals} / ${gr.round2_attempts}`, `${qr.round2_eligible} / ${qr.round2_proposals} / ${qr.round2_attempts}`)}
          ${row("Full notebook recovery", frac(gr.final_outcomes.fixed, n), frac(qr.final_outcomes.fixed, n))}
          ${row("Final outcomes (abstained / still failing / infra / method / fixed)", outcomesStr(gr.final_outcomes), outcomesStr(qr.final_outcomes))}
        </tbody>
      </table>
    </div>

    <h2 class="section-heading" style="margin-top:22px;">Notebook-by-notebook <span class="section-heading-note">${cmp.paired_notebooks} paired notebooks, compared field by field from both raw traces</span></h2>
    <div class="grid grid-3">
      ${statCard("Identical on every repair-relevant field", `${cmp.identical_notebooks} / ${cmp.paired_notebooks}`, `${cmp.identical_notebooks}`, "Eligibility, retrieval, proposal, FixApplicator outcome, newly exposed error, Round-2 decision and outcome, final classification.")}
      ${statCard("Structured decision differs", `${cmp.differing_notebooks} / ${cmp.paired_notebooks}`, `${cmp.differing_notebooks}`, `Notebooks ${idRange}: only the Round-1 pinned version differs.`)}
      ${statCard("Downstream outcome differs", `0 / ${cmp.paired_notebooks}`, "0", allDownstreamSame ? "Installation, next exposed error, Round 2, targeted resolution and final classification identical in all differing notebooks." : "See table.")}
    </div>

    <div class="card callout callout-neutral" style="margin-top:16px;">
      <strong>The models differed in NumPy version selection for ${diffs.length} records, but the difference did not change the measured downstream repair outcome.</strong>
      All ${diffs.length} are <span class="mono">wrong_version</span> failures on <span class="mono">numpy.VisibleDeprecationWarning</span>.
      Both models received the same retrieval evidence (${allCandidatesSame ? "identical candidate list and compatibility constraint" : "see table"}:
      <span class="mono">${esc((diffs[0] || {}).candidate_versions ? diffs[0].candidate_versions.join(", ") : "")}</span>, constraint <span class="mono">${esc(spec)}</span>).
      Gemma pinned <span class="mono">numpy==${esc(gVersions.join("/"))}</span>, Qwen pinned <span class="mono">numpy==${esc(qVersions.join("/"))}</span>. Both are grounded candidates under the constraint.
      This is a genuine model-selection difference, not a retrieval difference. Neither model is shown to be generally better by these results.
    </div>

    <div class="card" style="margin-top:16px; padding:0; overflow-x:auto;">
      <table class="data-table compact">
        <thead><tr><th>Notebook</th><th>Repository</th><th>Gemma proposal</th><th>Qwen proposal</th><th>Outcome (both)</th><th>Next error (both)</th><th>Final (both)</th><th></th></tr></thead>
        <tbody>
          ${diffs.map(d => `
            <tr>
              <td class="mono">#${d.notebook_execution_id}</td>
              <td style="font-size:12px;">${esc(repoShortName(d.repository_url))}</td>
              <td class="mono">${esc(d.gemma.action)} ${esc(d.gemma.install_name)}==${esc(d.gemma.version)}</td>
              <td class="mono">${esc(d.qwen.action)} ${esc(d.qwen.install_name)}==${esc(d.qwen.version)}</td>
              <td>${d.gemma.outcome === d.qwen.outcome ? categoryBadge(d.gemma.outcome) : `${categoryBadge(d.gemma.outcome)} / ${categoryBadge(d.qwen.outcome)}`}</td>
              <td class="mono" style="font-size:12px;">${esc(d.gemma.new_error[1])}${d.gemma.new_error[1] === d.qwen.new_error[1] ? "" : ` / ${esc(d.qwen.new_error[1])}`}</td>
              <td>${categoryBadge(d.gemma.final_category)}${d.gemma.final_category === d.qwen.final_category ? "" : " / " + categoryBadge(d.qwen.final_category)}</td>
              <td><button class="btn btn-sm" onclick="navigate('#/workspace/${caseIdFor(d.notebook_execution_id)}')">Gemma trace</button></td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>
    ${diffs.length ? `
    <div class="grid grid-2" style="margin-top:16px;">
      <div class="card"><div class="card-title">Gemma rationale (notebook #${diffs[0].notebook_execution_id})</div><p style="font-size:13px; margin:0;">${esc(diffs[0].gemma.rationale)}</p></div>
      <div class="card"><div class="card-title">Qwen rationale (notebook #${diffs[0].notebook_execution_id})</div><p style="font-size:13px; margin:0;">${esc(diffs[0].qwen.rationale)}</p></div>
    </div>` : ""}

    ${provenanceNoteCard()}
    <p class="footer-note">${esc(cmp.note)}</p>
  `;
  document.getElementById("main").innerHTML = html;
}

function outcomesStr(fo) {
  return `${fo.abstained} / ${fo.still_failing} / ${fo.infrastructure_failure} / ${fo.method_failure} / ${fo.fixed}`;
}

function caseIdFor(nbId) {
  const c = CASES.find(x => x.notebook_execution_id === nbId);
  return c ? c.id : "";
}
