/* Dark-mode persistence. initTheme() runs in main.jsx before React renders,
   so the first paint is already right. */

const STORAGE_KEY = "tradium-theme";

export function initTheme() {
  // An explicit choice wins; otherwise light (the landing page doesn't look
  // good in dark mode, so we don't follow the OS preference).
  const stored = localStorage.getItem(STORAGE_KEY);
  const dark = stored === "dark";

  document.documentElement.classList.toggle("dark", dark);
}

export function toggleTheme() {
  const dark = !document.documentElement.classList.contains("dark");
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem(STORAGE_KEY, dark ? "dark" : "light");
  return dark;
}
