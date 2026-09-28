/* Light/dark theme. The initial theme is applied synchronously by an inline
   script in <head> (before first paint); this file only exposes the shared
   setter. The toggle control itself lives on the Settings page. */

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("theme", theme); } catch (e) {}
}
