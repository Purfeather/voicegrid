import type { ThemeDefinition, ThemeId } from "../types";

export const THEMES: Record<ThemeId, ThemeDefinition> = {
  dark: { id: "dark", name: "炭黑荧光", colorScheme: "dark" },
  light: { id: "light", name: "纯白 AI", colorScheme: "light" },
};

const STORAGE_KEY = "longrong-theme-v2";

export function loadTheme(): ThemeId {
  const value = window.localStorage.getItem(STORAGE_KEY);
  return value === "light" ? "light" : "dark";
}

export function applyTheme(theme: ThemeId): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = THEMES[theme].colorScheme;
  window.localStorage.setItem(STORAGE_KEY, theme);
}
