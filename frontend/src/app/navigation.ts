import { useSyncExternalStore } from "react";
import type { MouseEvent } from "react";

export type AppPath = "/register" | "/verify" | "/login" | "/devices" | "/recover";

const paths: readonly AppPath[] = ["/register", "/verify", "/login", "/devices", "/recover"];

function currentPath(): AppPath {
  const pathname = window.location.pathname as AppPath;
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
  if (window.location.pathname !== path) {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
}

export function interceptNavigation(event: MouseEvent<HTMLAnchorElement>, path: AppPath): void {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  navigate(path);
}
