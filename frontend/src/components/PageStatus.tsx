import type { PropsWithChildren, ReactElement } from "react";
type StatusKind = "loading" | "notice" | "error" | "empty";
export function PageStatus({ kind, children }: PropsWithChildren<{ readonly kind: StatusKind }>): ReactElement {
  return <div className={`page-status page-status--${kind}`} role={kind === "error" ? "alert" : "status"} aria-live="polite">
    {kind === "loading" ? <span className="spinner" aria-hidden="true" /> : null}<div>{children}</div>
  </div>;
}
