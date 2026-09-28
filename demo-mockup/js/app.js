function parseHash() {
  const h = (window.location.hash || "#/dashboard").replace(/^#\/?/, "");
  const parts = h.split("/").filter(Boolean);
  return { route: parts[0] || "dashboard", arg: parts[1], arg2: parts[2] };
}

function setActiveNav(route) {
  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.route === route);
  });
}

function router() {
  const { route, arg, arg2 } = parseHash();
  setActiveNav(route === "workspace" ? "workspace" : route);
  try {
    switch (route) {
      case "dashboard": renderDashboard(); break;
      case "notebooks": renderNotebooks(); break;
      case "workspace": renderWorkspace(arg, arg2); break;
      case "evaluation": renderEvaluation(); break;
      case "comparison": renderComparison(); break;
      case "kg": renderKg(arg); break;
      case "settings": renderSettings(); break;
      default: renderDashboard();
    }
  } catch (err) {
    console.error(err);
    document.getElementById("main").innerHTML = `
      <div class="empty-note">Something went wrong rendering this page (${esc(err.message)}).
      Try the Overview page from the sidebar.</div>`;
  }
  window.scrollTo(0, 0);
}

document.querySelectorAll(".nav-item").forEach(el => {
  el.addEventListener("click", () => navigate("#/" + el.dataset.route));
});

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);
