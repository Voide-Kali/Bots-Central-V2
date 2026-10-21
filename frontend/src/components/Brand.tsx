import type { ReactElement } from "react";

/** The Aval signature: a handwritten-style wordmark with the "visto" (check) that approves. */
export function Brand({ withTagline = false }: { readonly withTagline?: boolean }): ReactElement {
  return <span className="brand">
    <span className="brand__mark" aria-hidden="true">
      <svg viewBox="0 0 40 24" focusable="false"><path d="M3 13.5c3.2 2.4 5.6 5.2 7.4 8C15.6 12.8 24 5.4 37 2.5" /></svg>
    </span>
    <span className="brand__word">aval</span>
    {withTagline ? <span className="brand__tagline">a IA que só age com o seu aval</span> : null}
  </span>;
}
