/* Shared formatting / small render helpers used across pages. */

function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function safe(v, fallback) {
  if (v === null || v === undefined || v === "") return fallback === undefined ? "—" : fallback;
  return v;
}

function labelize(s) {
  if (s === null || s === undefined || s === "") return "—";
  return String(s).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function fmtPct(x, digits) {
  if (x === null || x === undefined || x === "") return "—";
  const n = typeof x === "string" ? parseFloat(x) : x;
  if (Number.isNaN(n)) return "—";
  return (n * 100).toFixed(digits === undefined ? 1 : digits) + "%";
}

function fmtFraction(num, den) {
  return `${num} / ${den}`;
}

// category -> badge visual kind
// infrastructure_failure and method_failure are deliberately distinct: the
// evaluation methodology only calls a failure "infrastructure" when there is
// clear external/environment evidence, and leaves ambiguous cases as
// "method". Rendering them identically would erase that distinction.
const CATEGORY_BADGE = {
  fixed: "good",
  still_failing: "bad",
  abstained: "warn",
  infrastructure_failure: "infra",
  method_failure: "method",
  excluded: "neutral",
  unknown: "neutral",
};

function categoryBadge(cat) {
  if (!cat) return badge("—", "neutral");
  const kind = CATEGORY_BADGE[cat] || "neutral";
  return badge(labelize(cat), kind);
}

function badge(text, kind) {
  kind = kind || "neutral";
  return `<span class="badge badge-${kind}">${esc(text)}</span>`;
}

// per_notebook_comparison.csv stores booleans as literal strings "True"/"False"/"" (blank = n/a)
function parseBoolStr(v) {
  if (v === "True") return true;
  if (v === "False") return false;
  return null;
}

function boolBadge(b, trueLabel, falseLabel) {
  if (b === null || b === undefined) return badge("Not applicable", "neutral");
  return b ? badge(trueLabel || "Yes", "good") : badge(falseLabel || "No", "bad");
}

function kv(label, valueHtml) {
  return `<div class="kv"><label>${esc(label)}</label><div class="val">${valueHtml}</div></div>`;
}

function kvGrid(pairs) {
  return `<div class="kv-grid">${pairs.map(p => kv(p[0], p[1])).join("")}</div>`;
}

function repoShortName(url) {
  if (!url) return "—";
  const m = String(url).match(/github\.com\/([^\/]+\/[^\/]+)/);
  return m ? m[1] : url;
}

function navigate(hash) {
  window.location.hash = hash;
}
