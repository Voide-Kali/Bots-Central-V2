import { useSyncExternalStore } from "react";
import type { MouseEvent } from "react";

export type AppPath = "/register" | "/verify" | "/login" | "/devices" | "/recover";

const paths: readonly AppPath[] = ["/register", "/verify", "/login", "/devices", "/recover"];

// The panel is served under this base path: Caddy routes /painel/* to the SPA and Vite builds
// assets with `base: "/painel/"`. Keep the three in sync. The internal AppPath values stay
// root-relative ("/login"); only the real URL carries the prefix.
const BASE = "/painel";

function stripBase(pathname: string): string {
  if (pathname === BASE) return "/";
  return pathname.startsWith(BASE + "/") ? pathname.slice(BASE.length) : pathname;
}

// Real URL for an in-app path, e.g. appHref("/login") === "/painel/login". Use it for <a href>.
export function appHref(path: AppPath): string {
  return BASE + path;
}

function currentPath(): AppPath {
  const pathname = stripBase(window.location.pathname) as AppPath;
  return paths.includes(pathname) ? pathname : "/login";
}

function subscribe(listener: () => void): () => void {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
}

export function useAppPath(): AppPath {
  return useSyncExternalStore(subscribe, currentPath, () => "/login");
}

export function navigate(path: AppPath): void {
  const target = BASE + path;
  if (window.location.pathname !== target) {
    window.history.pushState({}, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
}

export function interceptNavigation(event: MouseEvent<HTMLAnchorElement>, path: AppPath): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  navigate(path);
}
