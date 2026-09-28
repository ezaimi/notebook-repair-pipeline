/* ---------------------------------------------------------------------
   Pipeline Trace demo.

   Renders recorded pipeline artefacts. There is no execution here: every
   value shown is read out of data/pipeline_demo.js, which is extracted
   from a stored run. No button runs a repair, and nothing contacts PyPI,
   Docker, GitHub or a model server.
--------------------------------------------------------------------- */

(function () {
  "use strict";

  // data/pipeline_demo.js declares `const PIPELINE_DEMO`, which lives in the
  // global lexical scope rather than on `window`, so it is referenced directly.
  const DATA = PIPELINE_DEMO;
  const RECORDS = DATA.records;
  const BY_ID = new Map(RECORDS.map(r => [r.id, r]));
  const PROV = DATA.provenance;

  /* ----------------------------- helpers ---------------------------- */

  function esc(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  const DASH = "&mdash;";

  function or(v, fallback) {
    if (v === null || v === undefined || v === "") return fallback === undefined ? DASH : fallback;
    return esc(v);
  }

  function words(s) {
    if (s === null || s === undefined || s === "") return DASH;
    return esc(String(s).replace(/_/g, " "));
  }

  function chip(text, cls) {
    return `<span class="chip ${cls || "chip-neutral"}">${esc(text)}</span>`;
  }

  function monoChip(text, cls) {
    return `<span class="chip chip-mono ${cls || "chip-neutral"}">${esc(text)}</span>`;
  }

  function yesNo(v, yes, no) {
    if (v === null || v === undefined) return chip("not recorded", "chip-neutral");
    return v ? chip(yes || "yes", "chip-good") : chip(no || "no", "chip-bad");
  }

  function kv(label, valueHtml, mono) {
    return `<div class="kv"><label>${esc(label)}</label>` +
           `<div class="v${mono ? " mono" : ""}">${valueHtml}</div></div>`;
  }

  function kvs(pairs) {
    return `<div class="kvs">${pairs.join("")}</div>`;
  }

  function card(step, title, who, bodyHtml) {
    const stepHtml = step ? `<span class="card-step">${esc(step)}</span>` : "";
    const whoHtml = who ? `<span class="spacer"></span><span class="who">${esc(who)}</span>` : "";
    return `<section class="card"><div class="card-head">${stepHtml}` +
           `<h3>${esc(title)}</h3>${whoHtml}</div>` +
           `<div class="card-body">${bodyHtml}</div></section>`;
  }

  function seconds(v) {
    if (v === null || v === undefined) return DASH;
    return esc(Number(v).toFixed(1)) + "&nbsp;s";
  }

  function shortSha(sha) {
    return sha ? esc(String(sha).slice(0, 10)) : DASH;
  }

  function repoName(url) {
    if (!url) return DASH;
    const m = String(url).match(/github\.com\/([^\/]+\/[^\/]+)/);
    return esc(m ? m[1] : url);
  }

  /* ------------------- derived labels (display only) ---------------- */

  // Outcome of the last recorded round. "abstained" is not an outcome the
  // applier reported - it is the recorded decision status, shown as such.
  function finalLabel(rec) {
    if (rec.final.decision_status === "abstained" && !rec.final.outcome) return "abstained";
    return rec.final.outcome || "not recorded";
  }

  function outcomeChip(outcome) {
    if (!outcome) return chip("not recorded", "chip-neutral");
    const map = {
      fixed: "chip-good",
      still_failing: "chip-bad",
      apply_error: "chip-warn",
      abstained: "chip-warn",
    };
    return chip(String(outcome).replace(/_/g, " "), map[outcome] || "chip-neutral");
  }

  function scopeChip(scope) {
    if (!scope) return chip("not recorded", "chip-neutral");
    if (scope === "usable") return chip("in repair scope", "chip-good");
    if (scope === "excluded") return chip("outside repair scope", "chip-warn");
    return chip(String(scope).replace(/_/g, " "), "chip-neutral");
  }

  // How the repair name/version was decided, in reader-facing words.
  function decisionSourceLabel(round) {
    const d = round.decision;
    if (d.status === "abstained") return "abstained - no verified evidence";
    if (d.source === "llm_select_from_verified_versions") return "model chose among verified releases";
    if (d.source === "deterministic_verified_install") {
      const p = round.mapping.model_proposal;
      if (p && p.verification_status === "resolved") return "deterministic install of a verified model proposal";
      return "deterministic install";
    }
    return d.source ? String(d.source).replace(/_/g, " ") : "not recorded";
  }

  /* ---------------------------- dashboard --------------------------- */

  const FILTERS = [
    { key: "all", label: "All records", test: () => true },
    { key: "fixed", label: "Repaired (Docker confirmed)", test: r => r.final.outcome === "fixed" },
    { key: "round2", label: "Ran a second round", test: r => r.rounds.length > 1 },
    { key: "explain_only", label: "New error explained only", test: r => !!r.explain_only },
    { key: "abstained", label: "Abstained", test: r => r.final.decision_status === "abstained" },
    { key: "model", label: "Model involved in repair", test: r => r.rounds.some(rd =>
        !!rd.decision.model || !!rd.mapping.model_proposal) },
    { key: "curated", label: "Curated mapping used", test: r => r.rounds.some(rd =>
        rd.mapping.resolved_method === "explicit_mismatch_mapping") },
  ];

  let activeFilter = "all";

  function provenanceStrip() {
    return `<div class="prov">
      ${provCell("Recorded run", PROV.run_id)}
      ${provCell("Model", PROV.model + " (Ollama)")}
      ${provCell("Split", PROV.split)}
      ${provCell("Records", PROV.actual_record_count + " / " + PROV.expected_record_count)}
      ${provCell("Round cap", String(PROV.max_rounds))}
      ${provCell("Integrity checks", PROV.checks_passed + " / " + PROV.checks_total + " passed")}
      ${provCell("Code commit", String(PROV.git_commit_sha).slice(0, 10))}
      ${provCell("Recorded", String(PROV.created_at).slice(0, 10))}
    </div>`;
  }

  function provCell(label, value) {
    return `<div><label>${esc(label)}</label><div class="v">${esc(value)}</div></div>`;
  }

  function staticNotice() {
    return `<div class="notice"><div>
      <b>This interface displays stored results only.</b> Every panel is read from the
      recorded trace of the run named above. Nothing here executes a repair or contacts
      PyPI, Docker, GitHub or a model server, and no control on this page can change a
      recorded decision.
    </div></div>`;
  }

  function legend() {
    const items = [
      ["Requested import", "role-import", "the top-level import the notebook asked for"],
      ["Candidate distribution", "role-candidate", "a distribution name a mapping source proposed"],
      ["Verified distribution", "role-verified", "exists on PyPI and wheel evidence proves it provides the import"],
      ["Selected repair", "role-selected", "the decision recorded by RAGRepairAgent"],
      ["Applied repair", "role-applied", "the command FixApplicator actually ran"],
      ["Docker outcome", "role-docker", "the verdict of re-executing the notebook"],
    ];
    return `<div class="legend">
      <h2>How to read a trace</h2>
      <p>A repair moves an import name through these six roles. Each role keeps the same
         colour everywhere in this interface.</p>
      <div class="legend-items">
        ${items.map(([t, c, d]) => `<div class="legend-item">${chip(t, c)}<div>${esc(d)}</div></div>`).join("")}
      </div>
    </div>`;
  }

  function highlightCards() {
    return `<div class="highlights">${DATA.highlights.map(h => {
      const rec = BY_ID.get(h.id);
      if (!rec) return "";
      // One line per round: an import and the distribution resolved for *that*
      // round. Pairing round 1's import with round 2's distribution would
      // describe a mapping the run never made.
      const flow = rec.rounds.map(rd => {
        const dist = rd.pypi.distribution_name;
        return `<div class="hl-flow">
          ${rec.rounds.length > 1 ? `<span class="hl-round">R${esc(rd.round)}</span>` : ""}
          ${monoChip(rd.error.module || "?", "role-import")}
          <span class="arrow">&rarr;</span>
          ${dist ? monoChip(dist, rd.decision.action === "none" ? "role-candidate" : "role-verified")
                 : chip("no distribution resolved", "chip-warn")}
        </div>`;
      }).join("");
      return `<div class="hl" data-goto="${rec.id}">
        <div class="hl-top">
          <span class="hl-id">#${esc(rec.id)}</span>
          ${outcomeChip(finalLabel(rec))}
          ${rec.rounds.length > 1 ? chip(rec.rounds.length + " rounds", "chip-info") : ""}
          ${rec.explain_only ? chip("new error explained only", "chip-warn") : ""}
        </div>
        ${flow}
        <div class="hl-note">${esc(h.note)}</div>
      </div>`;
    }).join("")}</div>`;
  }

  function filterBar() {
    return `<div class="filters">${FILTERS.map(f => {
      const n = RECORDS.filter(f.test).length;
      return `<button class="filter${f.key === activeFilter ? " active" : ""}" data-filter="${f.key}">
        ${esc(f.label)} <span class="n">${n}</span></button>`;
    }).join("")}</div>`;
  }

  function recordTable() {
    const f = FILTERS.find(x => x.key === activeFilter) || FILTERS[0];
    const rows = RECORDS.filter(f.test);
    if (!rows.length) return `<div class="empty">No records match this filter.</div>`;
    return `<p class="table-note">The import, distribution, mapping and decision columns
      describe round&nbsp;1. <em>Rounds</em> says whether a second round ran, and
      <em>final outcome</em> is the verdict of the last round.</p>
      <div class="card"><div class="table-scroll"><table class="grid">
      <thead><tr>
        <th>Record</th><th>Requested import</th><th>Distribution</th>
        <th class="wrap-h">Mapping source</th><th class="wrap-h">Repair decision</th>
        <th>Rounds</th><th class="wrap-h">Final outcome</th>
      </tr></thead>
      <tbody>${rows.map(rec => {
        // Round 1 throughout, so the import and the distribution on a row always
        // belong to the same round; the Rounds column carries the rest.
        const r1 = rec.rounds[0];
        const dist = r1.pypi.distribution_name;
        const verified = r1.decision.action !== "none";
        return `<tr class="clickable" data-goto="${rec.id}">
          <td class="num">#${esc(rec.id)}</td>
          <td>${monoChip(r1.error.module || "?", "role-import")}</td>
          <td>${dist ? monoChip(dist, verified ? "role-verified" : "role-candidate")
                     : `<span class="chip chip-warn">none resolved</span>`}</td>
          <td>${words(r1.mapping.resolved_method_label || r1.mapping.resolved_method)}</td>
          <td>${esc(decisionSourceLabel(r1))}</td>
          <td class="num">${rec.rounds.length}${rec.explain_only ? " + expl." : ""}</td>
          <td>${outcomeChip(finalLabel(rec))}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div></div>`;
  }

  function renderDashboard() {
    document.getElementById("view").innerHTML = `
      ${staticNotice()}
      ${provenanceStrip()}
      ${legend()}
      <div class="section-title">Highlighted traces &mdash; one per decision path</div>
      ${highlightCards()}
      <div class="section-title">All recorded notebooks</div>
      ${filterBar()}
      ${recordTable()}
      ${footer()}`;
    bindNav();
    document.querySelectorAll("[data-filter]").forEach(el => {
      el.addEventListener("click", () => {
        activeFilter = el.dataset.filter;
        renderDashboard();
      });
    });
  }

  function footer() {
    return `<div class="foot">
      Source trace: <code>${esc(PROV.trace_file)}</code><br/>
      Classifier context: <code>${esc(PROV.context_file)}</code><br/>
      Recorded ${esc(PROV.created_at)} from code commit <code>${shortSha(PROV.git_commit_sha)}</code>.
      Rebuild this page's data with <code>python demo-mockup/build_pipeline_demo_data.py</code>.
    </div>`;
  }

  /* --------------------------- trace view --------------------------- */

  // Three phases: reading the failure (1-3), grounding a repair (4-7),
  // applying it and recording the outcome (8-9).
  const PHASES = [
    { key: "read",   from: 0, to: 3, label: "Stages 1–3", sub: "failure, classification, explanation" },
    { key: "ground", from: 3, to: 7, label: "Stages 4–7", sub: "candidates, verification, decision" },
    { key: "apply",  from: 7, to: 9, label: "Stages 8–9", sub: "fix application, Docker, result" },
  ];

  function normalisePhase(p) {
    if (p === "analysis") return "read";      // earlier link form
    if (p === "result") return "apply";
    return PHASES.some(x => x.key === p) ? p : "read";
  }

  function stageRail(rec, round, phase) {
    const d = round.decision;
    const a = round.applied;
    const abstained = d.status === "abstained";
    const items = [
      ["1", "Failure", "done"],
      ["2", "Classification", "done"],
      ["3", "Explanation", round.explanation && round.explanation.status === "success" ? "done" : "stop"],
      ["4", "Candidates", round.mapping.deterministic_attempts.length || round.mapping.model_proposal ? "done" : "stop"],
      ["5", "Verification", round.pypi.candidates.length ? "done" : "stop"],
      ["6", "Requirements", round.requirements ? "done" : "skip"],
      ["7", "Decision", abstained ? "stop" : "done"],
      ["8", "Fix + Docker", abstained ? "skip" : "done"],
      ["9", "Result", "done"],
    ];
    const ph = PHASES.find(p => p.key === phase) || PHASES[0];
    return `<div class="rail">${items.map(([n, label, state], i) => {
      const active = i >= ph.from && i < ph.to;
      return (i ? `<span class="rail-sep">&rsaquo;</span>` : "") +
        `<span class="rail-item ${state}${active ? " phase-on" : ""}">
           <span class="dot"></span>${esc(n)}. ${esc(label)}</span>`;
    }).join("")}</div>`;
  }

  function stageFailure(rec, round) {
    const e = round.error;
    return card("1", "Recorded failure", "notebook execution", `
      ${kvs([
        kv("Error type", monoChip(e.type || "?", "chip-bad")),
        kv("Requested top-level import", monoChip(e.module || "?", "role-import")),
        kv("Failing cell index", or(rec.notebook.error_cell_index), true),
      ])}
      <p class="msg msg-bad" style="margin-top:12px">${esc(e.message)}</p>
      ${round.classification.signature && round.classification.signature.symbol
        ? `<p class="note">The classifier split this message into module
             <code>${esc(round.classification.signature.module_path)}</code> and symbol
             <code>${esc(round.classification.signature.symbol)}</code>. The repair layer
             works from the top-level import
             <code>${esc(e.module)}</code>.</p>`
        : `<p class="note">The repair layer resolves the top-level import name: a failure
             raised inside a submodule still counts as a failure of
             <code>${esc(e.module)}</code>.</p>`}
    `);
  }

  function stageClassification(rec, round) {
    const c = round.classification;
    return card("2", "Classification and scope check", "ErrorClassifier", `
      ${kvs([
        kv("Subtype", words(c.refined_subtype)),
        kv("Root-cause hint", words(c.root_cause_hint)),
        kv("Scope", scopeChip(c.scope_status)),
        kv("Classifier confidence", or(rec.classifier.confidence)),
        kv("Repair eligibility", c.eligibility === "usable"
          ? chip("eligible for automatic repair", "chip-good")
          : chip(String(c.eligibility || "not recorded").replace(/_/g, " "), "chip-warn")),
        kv("Context available", words(c.context_status)),
      ])}
      ${c.exclusion_reason ? `<p class="note">Exclusion reason: ${esc(c.exclusion_reason)}</p>` : ""}
      <p class="note">Only pip-installable third-party imports are eligible for automatic
        repair. Standard-library modules, imports local to the repository and
        system-level libraries are out of scope; they can still be explained.</p>
    `);
  }

  function stageExplanation(round) {
    const x = round.explanation;
    if (!x) {
      return card("3", "Explanation", "LLMExplainer", `
        <p>${chip("no explanation recorded for this round", "chip-neutral")}</p>
        <p class="note">Explanation and repair are independent: a missing explanation does
          not stop the repair path.</p>`);
    }
    if (x.status !== "success") {
      return card("3", "Explanation", "LLMExplainer", `
        ${kvs([
          kv("Status", chip(String(x.status || "failed").replace(/_/g, " "), "chip-warn")),
          kv("Model", x.model ? monoChip(x.model, "chip-model") : DASH),
          kv("Attempts", or(x.attempts), true),
        ])}
        ${x.error ? `<p class="msg msg-bad" style="margin-top:12px">${esc(x.error)}</p>` : ""}
        <p class="note">The repair path continued regardless: this run's explanation step
          cannot block or feed the repair decision.</p>`);
    }
    return card("3", "Explanation", "LLMExplainer", `
      ${kvs([
        kv("Model", monoChip(x.model, "chip-model")),
        kv("Self-reported confidence", or(x.confidence)),
        kv("Schema valid", yesNo(x.validation_errors.length === 0, "yes", "no")),
      ])}
      <div class="section-title" style="margin-top:16px">Reader-facing explanation</div>
      ${kvs([kv("Summary", esc(x.summary))])}
      <div style="margin-top:11px">${kvs([kv("Root cause", esc(x.root_cause))])}</div>
      ${x.evidence.length ? `<div style="margin-top:11px">
        <div class="kv"><label>Evidence cited</label></div>
        <ul class="tight">${x.evidence.map(e => `<li>${esc(e)}</li>`).join("")}</ul></div>` : ""}
      ${x.limitations ? `<div style="margin-top:11px">${kvs([kv("Stated limitations", esc(x.limitations))])}</div>` : ""}
      <p class="note">This text is written for a reader. It is not used as evidence for the
        repair decision, which is grounded in the verification of stages 4&ndash;7.</p>
    `);
  }

  function stageCandidates(round) {
    const m = round.mapping;
    const attempts = m.deterministic_attempts;
    const p = m.model_proposal;
    const rows = attempts.length ? `<div class="table-scroll"><table class="grid">
        <thead><tr><th>Order</th><th class="wrap-h">Deterministic source</th>
          <th class="wrap-h">Candidate distribution</th><th>Result</th></tr></thead>
        <tbody>${attempts.map((a, i) => `<tr>
          <td class="num">${i + 1}</td>
          <td>${words(a.mapping_label || a.mapping_method)}</td>
          <td>${monoChip(a.distribution_name || "?", "role-candidate")}</td>
          <td>${a.status === "resolved"
                ? chip("resolved", "chip-good")
                : chip(String(a.status).replace(/_/g, " "), "chip-warn")}
              ${a.error ? `<div class="note" style="margin-top:5px;border:0;padding:0">${esc(a.error)}</div>` : ""}</td>
        </tr>`).join("")}</tbody></table></div>`
      : `<p>${chip("no deterministic source produced a candidate", "chip-warn")}</p>`;

    const proposal = p ? `
      <div class="section-title" style="margin-top:18px">Model proposal (deterministic sources exhausted)</div>
      ${kvs([
        kv("Proposed distribution", monoChip(p.suggested_distribution || "?", "role-candidate")),
        kv("Model", p.model ? monoChip(p.model, "chip-model") : DASH),
        kv("Recorded role", words(p.role)),
        kv("Verification result", p.verification_status === "resolved"
          ? chip("passed PyPI and wheel verification", "chip-good")
          : chip(String(p.verification_status || "not recorded").replace(/_/g, " "), "chip-bad")),
      ])}
      ${p.rationale ? `<div style="margin-top:11px">${kvs([kv("Stated rationale", esc(p.rationale))])}</div>` : ""}
      <p class="note">The model may propose one additional distribution name when every
        deterministic source fails. The proposal is only a candidate: it has to pass the
        same PyPI and wheel checks before it can be installed.</p>` : "";

    return card("4", "Candidate generation", "RAGRepairAgent", `
      ${rows}
      <p class="note">Deterministic sources are tried in a fixed order: curated mappings,
        same-name lookup, PEP 503 normalisation, then a public import-to-distribution
        mapping.</p>
      ${proposal}
    `);
  }

  function stageVerification(round) {
    const p = round.pypi;
    const cands = p.candidates;
    const head = kvs([
      kv("Distribution checked", p.distribution_name ? monoChip(p.distribution_name, "role-candidate") : DASH),
      kv("Exists on PyPI", yesNo(p.package_found, "yes", "no")),
      kv("Verified releases", `${cands.length}`, true),
      kv("Target Python", or(p.python_version), true),
    ]);

    if (!cands.length) {
      return card("5", "PyPI and wheel verification", "PyPIRetriever", `
        ${head}
        <p class="msg msg-bad" style="margin-top:12px">${esc(p.error || "No verified candidate was produced.")}</p>
        <p class="note">A candidate is not safe merely because a similarly named project
          exists on PyPI. Without wheel evidence that the distribution provides the
          requested import, no candidate is passed on for repair.</p>
        ${p.source_endpoint ? `<div style="margin-top:11px">${kvs([kv("Index endpoint", `<code>${esc(p.source_endpoint)}</code>`)])}</div>` : ""}
      `);
    }

    return card("5", "PyPI and wheel verification", "PyPIRetriever", `
      ${head}
      <div class="section-title" style="margin-top:16px">Import evidence per release</div>
      <div class="table-scroll"><table class="grid">
        <thead><tr><th class="wrap-h">Verified release</th><th class="wrap-h">Requires Python</th>
          <th class="wrap-h">Import evidence</th><th class="wrap-h">Declared top-level imports</th></tr></thead>
        <tbody>${cands.map(c => `<tr>
          <td>${monoChip(c.version, "role-verified")}
              ${c.wheel_filename ? `<div class="sub-mono">${esc(c.wheel_filename)}</div>` : ""}</td>
          <td class="num">${or(c.requires_python)}</td>
          <td>${c.import_status === "verified"
                ? chip("verified", "chip-good")
                : chip(String(c.import_status || "none").replace(/_/g, " "), "chip-warn")}</td>
          <td>${c.top_level_imports.length
                ? c.top_level_imports.map(t => monoChip(t, "role-import")).join(" ")
                : DASH}</td>
        </tr>`).join("")}</tbody></table></div>
      ${kvs([
        kv("Index endpoint", `<code>${esc(p.source_endpoint || "")}</code>`),
        kv("Release window", p.compatibility_meaning ? esc(p.compatibility_meaning) : DASH),
      ])}
      <p class="note">Evidence comes from the wheel's <code>top_level.txt</code> and
        <code>RECORD</code>. A release only becomes a verified candidate when it declares
        the requested import.</p>
      ${p.warnings.length ? `<details class="drop"><summary>Retriever warnings
        (${p.warnings.length})</summary>
        <ul class="tight">${p.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
    `);
  }

  function stageRequirements(round) {
    const r = round.requirements;
    if (!r) {
      return card("6", "Repository dependency context", "requirements evidence", `
        <p>${chip("not evaluated", "chip-neutral")}</p>
        <p class="note">No verified candidate existed to compare a declaration against, so
          this step recorded nothing for this round.</p>`);
    }
    const statusChip = {
      declared_constraint_compatible: ["compatible with the verified candidates", "chip-good"],
      declared_constraint_conflicting: ["conflicts with the verified candidates", "chip-bad"],
      declared_constraint_absent: ["no declaration found", "chip-neutral"],
    }[r.status] || [String(r.status || "").replace(/_/g, " "), "chip-neutral"];

    const decls = r.declarations.length ? `<div style="margin-top:12px">${kvs(
      r.declarations.map(d => kv(
        `${d.path || "declaration"}${d.line_number ? " line " + d.line_number : ""}`,
        `<code>${esc(d.raw || d.requirement || "")}</code>` +
        (d.active_for_runtime === false ? " " + chip("not active at runtime", "chip-warn") : "")
      ))
    )}</div>` : "";

    return card("6", "Repository dependency context", "requirements evidence", `
      ${kvs([
        kv("Declaration status", chip(statusChip[0], statusChip[1])),
        kv("Distribution", r.distribution_name ? monoChip(r.distribution_name, "role-candidate") : DASH),
      ])}
      ${decls}
      ${r.limitations.length ? `<div style="margin-top:10px">${kvs([kv("Limitations",
          r.limitations.map(l => words(l)).join("; "))])}</div>` : ""}
      <p class="note">Compared against the ${esc(String(r.comparison_basis || "").replace(/_/g, " "))}.
        A declaration is contextual evidence only: it never proves that a distribution
        provides the requested import and is not authority for the repair. FixApplicator
        still installs the repository's own dependencies when it rebuilds the environment.</p>
    `);
  }

  function stageDecision(round) {
    const d = round.decision;
    if (d.status === "abstained") {
      return card("7", "Repair decision", "RAGRepairAgent", `
        <div class="verdict warn"><span class="big">Abstained</span>
          <span class="by">no safe verified evidence to act on</span></div>
        ${d.errors.length ? `<div class="kv"><label>Recorded reasons</label></div>
          <ul class="tight">${d.errors.map(e => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
        <p class="note">Abstaining is a recorded outcome, not a failure to run. No command
          was produced, so FixApplicator had nothing to apply.</p>`);
    }
    const selected = d.version ? `${d.install_name}==${d.version}` : d.install_name;
    return card("7", "Repair decision", "RAGRepairAgent", `
      <div class="chain">
        <div class="chain-step"><label>Requested import</label>
          ${monoChip(round.error.module || "?", "role-import")}</div>
        <span class="arrow">&rarr;</span>
        <div class="chain-step"><label>Verified distribution</label>
          ${monoChip(round.pypi.distribution_name || "?", "role-verified")}</div>
        <span class="arrow">&rarr;</span>
        <div class="chain-step"><label>Selected repair</label>
          ${monoChip(selected || "?", "role-selected")}</div>
      </div>
      ${kvs([
        kv("Action", words(d.action)),
        kv("Decided by", esc(decisionSourceLabel(round))),
        kv("Validation", `${yesNo(d.schema_valid, "schema valid", "schema invalid")}
            ${yesNo(d.grounding_valid, "grounded in verified evidence", "not grounded")}`),
      ])}
      ${d.model ? `<div style="margin-top:12px">
        <div class="section-title" style="margin-top:0">Model involvement</div>
        ${kvs([
          kv("Model and role", `${monoChip(d.model.model, "chip-model")} ${words(d.model.role)}`),
          kv("Choice restricted to", `${round.pypi.candidates.length} verified releases`),
        ])}
        ${d.rationale ? `<div style="margin-top:10px">${kvs([kv("Stated rationale", esc(d.rationale))])}</div>` : ""}
        <p class="note">The model only picked a version from the verified list. It did not
          query PyPI, read wheel metadata, install anything or judge the result.</p>
      </div>` : `<p class="note">No model was involved in this decision: a single verified
        candidate was installed deterministically.</p>`}
      <div style="margin-top:12px"><div class="kv"><label>Recorded command</label>
        <div class="v"><p class="msg msg-cmd">${esc(d.command)}</p></div></div></div>
    `);
  }

  function stageApply(round) {
    const a = round.applied;
    if (a.status === "skipped" || !a.command) {
      return card("8", "Fix application and re-execution", "FixApplicator + Docker", `
        <p>${chip("skipped", "chip-neutral")} ${a.skip_reason ? words(a.skip_reason) : ""}</p>
        <p class="note">Nothing was applied because no repair was selected in this round.</p>`);
    }
    return card("8", "Fix application and re-execution", "FixApplicator + Docker", `
      <div class="kv"><label>Applied repair</label>
        <div class="v"><p class="msg msg-cmd">${esc(a.command)}</p></div></div>
      <div style="margin-top:13px">${kvs([
        kv("Install step exit code", monoChip(String(a.return_code), a.return_code === 0 ? "chip-good" : "chip-bad")),
        kv("Repository checkout", words(a.commit_checkout_status)),
        kv("Commit", `<code>${shortSha(a.repository_commit)}</code>`),
        kv("Re-execution wall time", seconds(a.elapsed_seconds)),
      ])}</div>
      <p class="note">FixApplicator rebuilds the container, installs the repository's own
        dependencies, applies the single validated repair above and re-runs the notebook
        from its first cell.</p>
    `);
  }

  function stageResult(rec, round, isLast) {
    const a = round.applied;
    const next = round.next_round;
    const outcome = a.outcome;
    const kind = outcome === "fixed" ? "good" : (outcome === "still_failing" ? "bad" : "warn");

    let verdict;
    if (!outcome) {
      verdict = `<div class="verdict warn"><span class="big">No re-execution</span>
        <span class="by">no repair was applied in this round</span></div>`;
    } else {
      verdict = `<div class="verdict ${kind}">
        <span class="big">${esc(String(outcome).replace(/_/g, " "))}</span>
        <span class="by">decided by re-executing the notebook in Docker, not by the model</span>
      </div>`;
    }

    const newError = a.new_error_type ? `
      <div class="section-title" style="margin-top:4px">Error after the repair</div>
      ${kvs([
        kv("Original error recurred", yesNo(a.same_as_original_error === true, "yes", "no")),
        kv("New error type", monoChip(a.new_error_type, "chip-bad")),
      ])}
      <p class="msg msg-bad" style="margin-top:11px">${esc(a.new_error_message)}</p>` : "";

    let nextHtml = "";
    if (next && next.triggered) {
      nextHtml = `<div class="banner" style="margin:14px 0 0">
        <div class="body"><h4>A second round was started</h4>
        <p>The re-execution exposed a different dependency error that is itself eligible for
           repair (recorded reason: <code>${esc(next.reason)}</code>). Two rounds is the hard
           cap; there is no third.</p></div></div>`;
    } else if (next && next.reason && isLast) {
      const stopText = {
        round1_outcome_not_still_failing: "The notebook no longer failed on a repairable dependency error, so no further round was needed.",
        same_as_original_error: "The same error returned, so a second round would repeat a repair that has already been shown not to work.",
      }[next.reason];
      const excluded = String(next.reason).startsWith("new_error_not_repair_eligible");
      // Stopping because the notebook was repaired is not a caution.
      const tone = next.reason === "round1_outcome_not_still_failing" ? "banner-calm" : "banner-stop";
      if (stopText || excluded) {
        nextHtml = `<div class="banner ${tone}" style="margin:14px 0 0">
          <div class="body"><h4>No further round</h4>
          <p>${esc(stopText || "The newly exposed error is outside the pip-only repair scope, so it was explained but not repaired.")}
             Recorded reason: <code>${esc(next.reason)}</code>.</p></div></div>`;
      }
    }

    return card("9", `Result of round ${round.round}`, "ResultLogger", `
      ${verdict}
      ${newError}
      ${nextHtml}
    `);
  }

  function explainOnlyPanel(rec) {
    const x = rec.explain_only;
    if (!x) return "";
    const body = x.explanation;
    return `<div class="section-title">Newly exposed error: explained, not repaired</div>
      ${card("", "Out-of-scope failure after the repair", "ErrorClassifier + LLMExplainer", `
        ${kvs([
          kv("Error type", monoChip(x.error_type || "?", "chip-bad")),
          kv("Failing module", monoChip(x.failing_module || "not applicable", "chip-neutral")),
          kv("Subtype", words(x.refined_subtype)),
          kv("Scope", scopeChip(x.scope_status)),
        ])}
        <p class="msg msg-bad" style="margin-top:12px">${esc(x.error_message)}</p>
        ${x.exclusion_reason ? `<div style="margin-top:12px">${kvs([
          kv("Why repair stopped", esc(x.exclusion_reason))])}</div>` : ""}
        ${body && body.status === "success" ? `
          <div class="section-title" style="margin-top:16px">Explanation of the new error</div>
          ${kvs([
            kv("Model", body.model ? monoChip(body.model, "chip-model") : DASH),
            kv("Self-reported confidence", or(body.confidence)),
          ])}
          <div style="margin-top:11px">${kvs([kv("Summary", esc(body.summary))])}</div>
          <div style="margin-top:11px">${kvs([kv("Root cause", esc(body.root_cause))])}</div>
          ${body.limitations ? `<div style="margin-top:11px">${kvs([
            kv("Stated limitations", esc(body.limitations))])}</div>` : ""}` : ""}
        <p class="note">The explanation of this error exists in the trace on its own. Because
          the error is outside the pip-only repair scope, no repair round followed it.</p>
      `)}`;
  }

  function renderTrace(id, roundNo, phase) {
    const rec = BY_ID.get(Number(id));
    if (!rec) {
      document.getElementById("view").innerHTML =
        `<div class="empty">No record #${esc(id)} in this run.
         <a href="#/records">Back to the record list</a>.</div>`;
      return;
    }
    const idx = Math.max(0, Math.min(rec.rounds.length - 1, (Number(roundNo) || 1) - 1));
    const round = rec.rounds[idx];
    const isLast = idx === rec.rounds.length - 1;
    phase = normalisePhase(phase);

    const roundTabs = rec.rounds.length > 1 ? `<div class="tabs">${rec.rounds.map((r, i) =>
      `<button class="tab${i === idx ? " active" : ""}" data-round="${r.round}">Round ${r.round}</button>`
    ).join("")}</div>` : "";

    const banner = round.entered_because ? `<div class="banner">
      <div class="body"><h4>Why round ${round.round} ran</h4>
      <p>Round ${round.round - 1} removed the original failure, and re-execution then stopped on a
         <em>different</em> dependency error that is itself eligible for repair:
         <code>${esc(round.entered_because.error_type)}: ${esc(round.entered_because.error_message)}</code>.
         The pipeline reclassified that error
         (<code>${esc(round.entered_because.context_status)}</code>) and repaired it once more.
         Two rounds is the cap.</p></div></div>` : "";

    // Each phase is laid out in two columns so it fits one screen.
    const bodies = {
      read: `<div class="cols">
        <div>${stageFailure(rec, round)}${stageClassification(rec, round)}</div>
        <div>${stageExplanation(round)}</div>
      </div>`,
      ground: `<div class="cols">
        <div>${stageCandidates(round)}${stageVerification(round)}</div>
        <div>${stageRequirements(round)}${stageDecision(round)}</div>
      </div>`,
      apply: `<div class="cols">
        <div>${stageApply(round)}${stageResult(rec, round, isLast)}</div>
        <div>${isLast ? explainOnlyPanel(rec) + finalSummary(rec) : ""}</div>
      </div>`,
    };

    document.getElementById("view").innerHTML = `
      <div class="crumb"><a href="#/records">&larr; All records</a> &nbsp;&middot;&nbsp;
        record #${esc(rec.id)} of run <code>${esc(PROV.run_id)}</code></div>
      <div class="rec-head">
        <h2>${esc(rec.notebook.name || "notebook " + rec.id)}</h2>
        <div class="meta">${repoName(rec.notebook.repository_url)} &nbsp;&middot;&nbsp;
          commit <span class="mono">${shortSha(rec.notebook.repository_commit)}</span>
          &nbsp;&middot;&nbsp; ${rec.rounds.length} recorded round${rec.rounds.length > 1 ? "s" : ""}
          &nbsp;&middot;&nbsp; final: ${outcomeChip(finalLabel(rec))}</div>
      </div>
      ${roundTabs}
      ${stageRail(rec, round, phase)}
      <div class="tabs">${PHASES.map(p =>
        `<button class="tab${phase === p.key ? " active" : ""}" data-phase="${p.key}">
           ${p.label} <span class="count">&middot; ${esc(p.sub)}</span></button>`).join("")}
      </div>
      ${phase === "read" ? banner : ""}
      ${bodies[phase]}
      ${footer()}`;

    document.querySelectorAll("[data-round]").forEach(el => {
      el.addEventListener("click", () => {
        window.location.hash = `#/trace/${rec.id}/${el.dataset.round}/${phase}`;
      });
    });
    document.querySelectorAll("[data-phase]").forEach(el => {
      el.addEventListener("click", () => {
        window.location.hash = `#/trace/${rec.id}/${round.round}/${el.dataset.phase}`;
      });
    });
  }

  function finalSummary(rec) {
    const last = rec.rounds[rec.rounds.length - 1];
    const applied = rec.rounds
      .map(r => r.applied.command)
      .filter(Boolean);
    return `<div class="section-title">Final recorded state</div>
      ${card("", "What the run concluded for this notebook", "ResultLogger", `
        ${kvs([
          kv("Rounds run", `${rec.rounds.length} of ${PROV.max_rounds} permitted`, true),
          kv("Final outcome", outcomeChip(finalLabel(rec))),
          kv("Decided by", "Docker re-execution"),
          kv("Explanation recorded", rec.explanation_status === "success"
            ? chip("yes", "chip-good") : chip(String(rec.explanation_status || "none"), "chip-warn")),
        ])}
        ${applied.length ? `<div style="margin-top:13px"><div class="kv"><label>Repairs applied, in order</label></div>
          <ul class="tight">${applied.map(c => `<li><code>${esc(c)}</code></li>`).join("")}</ul></div>` : ""}
        ${last.applied.new_error_message && last.applied.outcome !== "fixed" ? `
          <p class="note">The notebook still fails after the last permitted round. The trace
            keeps the remaining error so the record stays auditable.</p>` : ""}
      `)}`;
  }

  /* ----------------------------- routing ---------------------------- */

  function bindNav() {
    document.querySelectorAll("[data-goto]").forEach(el => {
      el.addEventListener("click", () => {
        window.location.hash = `#/trace/${el.dataset.goto}`;
      });
    });
  }

  function route() {
    const raw = (window.location.hash || "#/records").replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    // ?shot=1 strips interactive chrome for figure capture
    if (new URLSearchParams(window.location.search).get("shot")) {
      document.body.classList.add("shot");
    }
    if (parts[0] === "trace" && parts[1]) {
      renderTrace(parts[1], parts[2], parts[3]);
    } else {
      renderDashboard();
    }
    window.scrollTo(0, 0);
  }

  window.addEventListener("hashchange", route);
  window.addEventListener("DOMContentLoaded", () => {
    const t = document.getElementById("theme-toggle");
    if (t) {
      t.addEventListener("click", () => {
        const now = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", now);
        try { localStorage.setItem("pipeline-demo-theme", now); } catch (e) {}
      });
    }
    route();
  });
})();
