function renderSettings() {
  const html = `
    <div class="page-header">
      <h1 class="page-title">Settings &amp; Provenance</h1>
      <p class="page-sub">Display preferences, and the recorded runs every screen of this demo replays.</p>
    </div>

    <div class="card" style="max-width:560px;">
      <div class="card-title">Appearance</div>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">Theme</div>
          <div class="settings-row-desc">Switch between light and dark mode.</div>
        </div>
        <button class="theme-toggle" id="theme-toggle" type="button" aria-label="Toggle dark mode" title="Toggle light / dark mode">
          <span class="theme-toggle-track">
            <span class="theme-toggle-icon" aria-hidden="true">&#9728;</span>
            <span class="theme-toggle-icon" aria-hidden="true">&#9789;</span>
            <span class="theme-toggle-thumb"></span>
          </span>
        </button>
      </div>
    </div>

    <div class="grid grid-2" style="margin-top:16px; max-width:1100px;">
      ${provenanceCard(EVALUATION.gemma, "Main run — every notebook replay uses this trace")}
      ${provenanceCard(EVALUATION.qwen, "Sensitivity run — used by the Gemma vs Qwen comparison only")}
    </div>

    <details class="card provenance-details" style="margin-top:16px; max-width:1100px;">
      <summary class="card-title" style="cursor:pointer; margin:0;">Execution environment note &middot; repository revision</summary>
      <p style="font-size:13px; margin:10px 0 0 0;">${esc(EVALUATION.commit_pinning_note)}</p>
    </details>

    <p class="footer-note" style="max-width:1100px;">${esc(EVALUATION.demo_note)} Values on this page are copied from each run's <span class="mono">manifest.json</span> and <span class="mono">validation_report.json</span>. Absolute local paths, tokens and environment files are not included in the demo data.</p>
  `;
  document.getElementById("main").innerHTML = html;

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const now = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    setTheme(now === "dark" ? "light" : "dark");
  });
}

function provenanceCard(run, subtitle) {
  const p = run.provenance;
  const allPassed = p.integrity_checks_passed === p.integrity_checks_total;
  const cfg = p.config_paths || {};
  return `
    <div class="card">
      <div class="card-title">${esc(run.model_label)}</div>
      <div class="settings-row" style="padding-bottom:10px;">
        <div class="settings-row-desc" style="margin-top:0;">${esc(subtitle)}</div>
        ${badge("Frozen — final", "accent")}
      </div>
      <div class="kv-grid">
        ${kv("Run ID", `<span class="mono" style="font-size:11.5px;">${esc(p.run_id)}</span>`)}
        ${kv("Split", `${labelize(p.split)} &middot; ${p.actual_record_count} / ${p.expected_record_count} records`)}
        ${kv("Model", `${esc(run.model)} via ${labelize(run.provider)}`)}
        ${kv("Git commit", `<span class="mono" style="font-size:11.5px;">${esc(p.git_commit_sha.slice(0, 12))}</span>`)}
        ${kv("Max rounds", `${p.max_rounds} (hard cap)`)}
        ${kv("Round-2 explanation", p.orchestrator_features && p.orchestrator_features.round2_explanation ? badge("Enabled — detected from orchestrator source", "good") : badge("Not detected", "warn"))}
        ${kv("Prompts", `${esc(p.explanation_prompt_version)} &middot; ${esc(p.repair_prompt_version)} &middot; ${esc(p.prompt_strategy)}`)}
        ${kv("Configs", `<span class="mono" style="font-size:11px;">${esc(cfg.explainer_config || "")}<br/>${esc(cfg.repair_config || "")}<br/>${esc(cfg.fix_config || "")}</span>`)}
        ${kv("Python", esc(p.python_version))}
        ${kv("Integrity checks", boolBadge(allPassed, `${p.integrity_checks_passed} / ${p.integrity_checks_total} passed`, `${p.integrity_checks_passed} / ${p.integrity_checks_total} passed`))}
      </div>
      <details class="raw-json" style="margin-top:10px;">
        <summary>Integrity checks run</summary>
        <ul class="check-list">${(p.integrity_check_names || []).map(n => `<li class="mono">${esc(n)}</li>`).join("")}</ul>
      </details>
    </div>
  `;
}
