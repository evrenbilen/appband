"use strict";

const FALLBACK_LOCALE = "en";
let _dict = {};
let _current = FALLBACK_LOCALE;

function _detect() {
  const stored = localStorage.getItem("appband.locale");
  if (stored) return stored;
  const nav = (navigator.language || "").toLowerCase();
  if (nav.startsWith("tr")) return "tr";
  return FALLBACK_LOCALE;
}

async function _loadDict(locale) {
  try {
    const r = await fetch(`/static/locales/${locale}.json`);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    console.warn(`[i18n] failed to load ${locale}; falling back to ${FALLBACK_LOCALE}`, e);
    if (locale !== FALLBACK_LOCALE) return _loadDict(FALLBACK_LOCALE);
    return {};
  }
}

export function t(key, vars) {
  let s = _dict[key];
  if (s === undefined) return key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replaceAll(`{${k}}`, String(v));
    }
  }
  return s;
}

function _applyDom(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const value = t(key);
    if (value !== key) el.textContent = value;
  });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    const value = t(key);
    if (value !== key) el.title = value;
  });
}

export async function initI18n() {
  _current = _detect();
  _dict = await _loadDict(_current);
  document.documentElement.lang = _current;
  _applyDom();
  return _current;
}

export async function setLocale(locale) {
  if (locale === _current) return;
  _dict = await _loadDict(locale);
  _current = locale;
  localStorage.setItem("appband.locale", locale);
  document.documentElement.lang = locale;
  _applyDom();
  window.dispatchEvent(new CustomEvent("locale-changed", { detail: { locale } }));
}

export function currentLocale() { return _current; }
export function applyDom(root) { _applyDom(root); }
