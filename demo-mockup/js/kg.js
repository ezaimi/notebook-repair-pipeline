/* Minimal knowledge-graph view. Node/edge labels are taken directly from
   the real RML mapping (mapping/rml_mapping/repair_attempts.rml.ttl):
   repr:hadRepairAttempt, repr:failingModule, repr:subtype, repr:explanation,
   repr:fixAction, repr:installName, repr:fixVersion, repr:fixOutcome,
   repr:llmModel, repr:round. Renders one notebook's RepairAttempt node(s)
   as a small star graph — not a full graph explorer. */

let kgCaseId = null;

function renderKg(caseId) {
  if (!caseId) caseId = kgCaseId || (CASES.find(c => c.showcase) || CASES[0]).id;
  kgCaseId = caseId;
  const c = CASES.find(x => x.id === caseId);

  const html = `
    <div class="page-header">
      <h1 class="page-title">Knowledge Graph</h1>
      <p class="page-sub">One notebook's RDF neighborhood, using the predicates defined in
        <span class="mono">mapping/rml_mapping/repair_attempts.rml.ttl</span>. This view renders one selected
        notebook at a time rather than the full graph.</p>
    </div>

    <div class="filter-bar">
      <label>Notebook</label>
      <select id="kg-select">
        ${CASES.map(x => `<option value="${x.id}" ${x.id === caseId ? "selected" : ""}>#${x.notebook_execution_id} — ${esc(x.original_error.failing_module)}${x.showcase ? " (showcase)" : ""}</option>`).join("")}
      </select>
    </div>

    <div class="card kg-canvas" id="kg-canvas"></div>

    <p class="footer-note">Node identifiers follow the mapping's subject templates:
      <span class="mono">reproduceme/notebook_{id}</span> and <span class="mono">reproduceme/repairattempt_{id}</span>.
      Attribute values shown are literal object values from the same triples map, taken from this notebook's real
      repair-attempt record(s).</p>
  `;
  document.getElementById("main").innerHTML = html;
  document.getElementById("kg-select").addEventListener("change", e => renderKg(e.target.value));

  renderKgCanvas(c);
}

function renderKgCanvas(c) {
  const canvas = document.getElementById("kg-canvas");
  canvas.innerHTML = `
    <div style="display:flex; flex-direction:column; align-items:center; gap:18px;">
      <div class="flow-node" style="border-color:var(--accent); background:var(--accent-soft);">
        <div class="flabel">Notebook</div>
        <div class="fval mono">notebook_${c.notebook_execution_id}</div>
      </div>
      <div style="font-size:12px; color:var(--text-faint);">&#8595; repr:hadRepairAttempt</div>
      <div style="display:flex; gap:24px; flex-wrap:wrap; justify-content:center;">
        ${c.rounds.map(r => repairAttemptSubgraph(c, r)).join("")}
      </div>
    </div>
  `;
}

// The explanation literal of a Round-1 row is the original failure's
// explanation; a Round-2 row carries the explanation of the newly exposed
// error that round targeted (trace: rounds[1].explanation == round2 trigger).
function explanationLiteral(c, r) {
  const e = r.round === 1 ? c.explanation : (c.round2 ? c.round2.explanation : null);
  if (!e || e.status !== "success") return "(absent - runtime failure, no literal)";
  const s = e.json.summary || "";
  return (r.round === 2 ? "[round-2 error] " : "") + (s.length > 70 ? s.slice(0, 70) + "…" : s);
}

function repairAttemptSubgraph(c, r) {
  const ra = r.repair_agent;
  const fa = r.fix_applicator;
  const edges = [
    ["repr:failingModule", r.classifier.failing_module],
    ["repr:subtype", r.classifier.subtype],
    ["repr:fixAction", ra.action || "none"],
    ra.install_name ? ["repr:installName", ra.install_name] : null,
    ra.version ? ["repr:fixVersion", ra.version] : null,
    fa.attempted ? ["repr:fixOutcome", fa.outcome] : null,
    ["repr:explanation", explanationLiteral(c, r)],
    ra.llm_model ? ["repr:llmModel", ra.llm_model] : null,
    ["repr:round", String(r.round)],
  ].filter(Boolean);

  return `
    <div style="display:flex; flex-direction:column; align-items:center; gap:10px; padding:12px; border:1px dashed var(--border); border-radius:10px;">
      <div class="flow-node">
        <div class="flabel">RepairAttempt &middot; Round ${r.round}</div>
        <div class="fval mono">repairattempt_${c.notebook_execution_id}_r${r.round}</div>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:8px; justify-content:center; max-width:360px;">
        ${edges.map(([p, v]) => `
          <div class="flow-node" style="padding:6px 10px;">
            <div class="flabel">${esc(p)}</div>
            <div class="fval mono" style="font-size:12px;">${esc(v)}</div>
          </div>`).join("")}
      </div>
    </div>
  `;
}
