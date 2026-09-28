/* Notebook Failures: all 187 evaluation notebooks of the final Gemma run, with
   filters that target the patterns the thesis discusses. */

const notebooksState = { subtype: "all", finalStatus: "all", quick: "all", query: "", page: 1, pageSize: 25 };

// Quick filters. Each predicate reads the flags build_demo_data.py derived
// from the recorded trace; the counts shown next to each option are computed
// from the loaded list, so they always match the displayed population.
const QUICK_FILTERS = [
  { key: "all", label: "All records", test: () => true },
  { key: "round2_reclassified", label: "Round 2 triggered (new error reclassified + explained)", test: r => r.flags.round2_reclassified },
  { key: "round2_eligible", label: "Round 2 repair-eligible", test: r => r.flags.round2_eligible },
  { key: "round2_attempted", label: "Round 2 repair applied", test: r => r.flags.round2_attempted },
  { key: "round2_abstained", label: "Round 2 abstained (mapping unknown)", test: r => r.flags.round2_abstained },
  { key: "round2_trace_only", label: "Explained but not repair-eligible (trace-only)", test: r => r.flags.round2_trace_only },
  { key: "round1_abstained", label: "Round 1 abstained", test: r => r.flags.round1_abstained },
  { key: "targeted_resolved", label: "Targeted error resolved", test: r => r.flags.targeted_resolved_any },
  { key: "same_error", label: "Repair applied, same error persists", test: r => r.flags.same_error_persisted },
  { key: "still_failing", label: "Still failing (final)", test: r => r.flags.still_failing },
  { key: "infrastructure_failure", label: "Infrastructure failure", test: r => r.flags.infrastructure_failure },
  { key: "method_failure", label: "Method failure", test: r => r.flags.method_failure },
  { key: "explanation_failed", label: "Original explanation: runtime failure", test: r => r.flags.explanation_runtime_failure },
  { key: "showcase", label: "Showcase notebooks", test: r => !!r.showcase },
];

function renderNotebooks() {
  const counts = {};
  QUICK_FILTERS.forEach(f => { counts[f.key] = NOTEBOOK_LIST.filter(f.test).length; });
  const html = `
    <div class="page-header">
      <h1 class="page-title">Notebook Failures</h1>
      <p class="page-sub">All ${NOTEBOOK_LIST.length} evaluation notebooks of the final Gemma-2 9B run (<span class="mono">${esc(EVALUATION.main_run_id)}</span>). Each row replays that notebook's recorded pipeline trace.</p>
    </div>

    <div class="filter-bar">
      <div>
        <label>Quick filter</label>
        <select id="f-quick">
          ${QUICK_FILTERS.map(f => `<option value="${f.key}">${esc(f.label)} (${counts[f.key]})</option>`).join("")}
        </select>
      </div>
      <div>
        <label>Subtype</label>
        <select id="f-subtype">
          <option value="all">All</option>
          <option value="missing_package">missing_package</option>
          <option value="wrong_version">wrong_version</option>
        </select>
      </div>
      <div>
        <label>Final status</label>
        <select id="f-final">
          <option value="all">All</option>
          <option value="abstained">abstained</option>
          <option value="still_failing">still_failing</option>
          <option value="infrastructure_failure">infrastructure_failure</option>
          <option value="method_failure">method_failure</option>
          <option value="fixed">fixed</option>
        </select>
      </div>
      <div>
        <label>Search</label>
        <input type="text" id="f-query" placeholder="id, module, repository" />
      </div>
      <div class="result-count" id="result-count"></div>
    </div>

    <div class="table-legend">
      <span><strong>Round 2 —</strong></span>
      <span>${badge("R2 repaired", "r2")} new error reclassified, explained, eligible, repaired</span>
      <span>${badge("R2 abstained", "warn")} eligible, but its import has no PyPI mapping</span>
      <span>${badge("explained only", "neutral")} new error explained, outside repair scope</span>
      <span class="small-caps">none: Round 1 exposed no new error</span>
    </div>

    <div class="card" style="padding:0; overflow-x:auto;">
      <table class="data-table" id="notebook-table"></table>
    </div>
    <div class="pager" id="pager"></div>

    <p class="footer-note">
      Scope note: ${EVALUATION.dataset.subtype_counts.system_library} <code>system_library</code> and
      ${EVALUATION.dataset.subtype_counts.mapping_unknown} classifier-level <code>mapping_unknown</code> records exist in the raw
      ${EVALUATION.dataset.total_rows}-record dataset but are excluded before repair (pip-only scope) and never reach this table.
      Within the usable records shown here, a repair attempt can still <em>abstain</em> because PyPI resolution returns
      <code>mapping_unknown</code> for that import name — a different, later-stage meaning of the same term.
    </p>
  `;
  document.getElementById("main").innerHTML = html;

  document.getElementById("f-quick").value = notebooksState.quick;
  document.getElementById("f-subtype").value = notebooksState.subtype;
  document.getElementById("f-final").value = notebooksState.finalStatus;
  document.getElementById("f-query").value = notebooksState.query;

  const onChange = key => e => { notebooksState[key] = e.target.value; notebooksState.page = 1; renderNotebookTable(); };
  document.getElementById("f-quick").addEventListener("change", onChange("quick"));
  document.getElementById("f-subtype").addEventListener("change", onChange("subtype"));
  document.getElementById("f-final").addEventListener("change", onChange("finalStatus"));
  document.getElementById("f-query").addEventListener("input", onChange("query"));
  renderNotebookTable();
}

function filteredNotebookRows() {
  let rows = NOTEBOOK_LIST.slice();
  const quick = QUICK_FILTERS.find(f => f.key === notebooksState.quick) || QUICK_FILTERS[0];
  rows = rows.filter(quick.test);
  if (notebooksState.subtype !== "all") rows = rows.filter(r => r.subtype === notebooksState.subtype);
  if (notebooksState.finalStatus !== "all") rows = rows.filter(r => r.final_category === notebooksState.finalStatus);
  const q = notebooksState.query.trim().toLowerCase();
  if (q) rows = rows.filter(r => String(r.notebook_execution_id) === q
    || (r.failing_module || "").toLowerCase().includes(q)
    || (r.round2_new_module || "").toLowerCase().includes(q)
    || (r.repository_url || "").toLowerCase().includes(q));
  return rows;
}

function renderNotebookTable() {
  const rows = filteredNotebookRows();
  document.getElementById("result-count").textContent = `${rows.length} of ${NOTEBOOK_LIST.length} shown`;
  const table = document.getElementById("notebook-table");
  const pager = document.getElementById("pager");

  if (rows.length === 0) {
    pager.innerHTML = "";
    table.innerHTML = `<tbody><tr><td style="padding:26px;"><div class="empty-note">
      No records match this filter.${notebooksState.finalStatus === "fixed" ? ` That matches the recorded result: 0 of ${NOTEBOOK_LIST.length} evaluation notebooks were fully fixed. See the Evaluation Summary for the targeted-error-resolution figure that tells the fuller story.` : ""}
    </div></td></tr></tbody>`;
    return;
  }

  const pageCount = Math.max(1, Math.ceil(rows.length / notebooksState.pageSize));
  if (notebooksState.page > pageCount) notebooksState.page = pageCount;
  const start = (notebooksState.page - 1) * notebooksState.pageSize;
  const pageRows = rows.slice(start, start + notebooksState.pageSize);

  table.innerHTML = `
    <thead>
      <tr>
        <th>Notebook</th>
        <th>Original error</th>
        <th>Subtype</th>
        <th>Explanation</th>
        <th>Round 1</th>
        <th>Round 2</th>
        <th>Final</th>
        <th></th>
      </tr>
    </thead>
    <tbody>${pageRows.map(rowHtml).join("")}</tbody>
  `;
  renderPager(rows.length, pageCount, start, pageRows.length);
}

function renderPager(totalRows, pageCount, start, shown) {
  const pager = document.getElementById("pager");
  if (pageCount <= 1) {
    pager.innerHTML = `<div class="pager-info">Showing all ${totalRows} record${totalRows === 1 ? "" : "s"}</div>`;
    return;
  }
  pager.innerHTML = `
    <div class="pager-info">Records ${start + 1}–${start + shown} of ${totalRows}</div>
    <div class="pager-controls">
      <button class="btn btn-sm" id="pg-prev" ${notebooksState.page === 1 ? "disabled" : ""}>&larr; Previous</button>
      <span class="pager-page">Page ${notebooksState.page} of ${pageCount}</span>
      <button class="btn btn-sm" id="pg-next" ${notebooksState.page === pageCount ? "disabled" : ""}>Next &rarr;</button>
    </div>
  `;
  const prev = document.getElementById("pg-prev");
  const next = document.getElementById("pg-next");
  if (prev) prev.addEventListener("click", () => goToNotebookPage(notebooksState.page - 1));
  if (next) next.addEventListener("click", () => goToNotebookPage(notebooksState.page + 1));
}

function goToNotebookPage(page) {
  notebooksState.page = page;
  renderNotebookTable();
  document.getElementById("notebook-table").scrollIntoView({ block: "start", behavior: "smooth" });
}

function round1Cell(r) {
  if (r.round1_category === "abstained") return `${badge("Abstained", "warn")}<div class="cell-sub">no PyPI mapping</div>`;
  const prop = r.round1_proposal ? `<div class="cell-sub mono">${esc(r.round1_action)} ${esc(r.round1_proposal)}</div>` : "";
  if (r.round1_outcome === "apply_error") return `${categoryBadge(r.round1_category)}${prop}`;
  const resolved = r.targeted_error_resolved_round1 === true;
  return `${badge(resolved ? "Target resolved" : "Same error persists", resolved ? "good" : "bad")}${prop}`;
}

function round2Cell(r) {
  if (!r.round2_reclassified) return `<span class="small-caps">none</span>`;
  const head = `<div class="cell-sub">new: <span class="mono">${esc(r.round2_new_module || "")}</span> &middot; ${esc(labelize(r.round2_new_subtype))} &middot; ${r.round2_explanation_status === "success" ? "explained" : "explanation failed"}</div>`;
  if (r.round2_status === "attempted") {
    const resolved = r.targeted_error_resolved_round2 === true;
    return `${badge("R2 repaired", "r2")} ${badge(resolved ? "target resolved" : "not resolved", resolved ? "good" : "bad")}${head}`;
  }
  if (r.round2_status === "abstained") return `${badge("R2 abstained", "warn")}${head}`;
  return `${badge("explained only", "neutral")}${head}<div class="cell-sub">not repair-eligible</div>`;
}

function rowHtml(r) {
  return `
    <tr>
      <td>
        <div class="mono">#${r.notebook_execution_id}</div>
        <div style="font-size:11.5px; color:var(--text-faint); max-width:220px;">${esc(repoShortName(r.repository_url))}</div>
        ${r.showcase ? `<div style="margin-top:3px;"><span class="badge badge-accent" title="${esc(r.showcase)}">Showcase</span></div>` : ""}
      </td>
      <td><div class="mono">${esc(r.error_type)}</div><div class="cell-sub mono">${esc(r.failing_module)}</div></td>
      <td>${esc(labelize(r.subtype))}</td>
      <td>${r.explanation_status === "success" ? badge("Completed", "good") : badge("Runtime failure", "warn")}</td>
      <td>${round1Cell(r)}</td>
      <td>${round2Cell(r)}</td>
      <td>${categoryBadge(r.final_category)}</td>
      <td><button class="btn btn-sm btn-primary" onclick="navigate('#/workspace/${r.case_id}')">Open</button></td>
    </tr>`;
}
