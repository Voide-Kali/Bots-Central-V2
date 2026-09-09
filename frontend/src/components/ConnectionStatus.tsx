import type { ReactElement } from "react";
import type { ProvisionalDevice } from "../api/contracts";

interface ConnectionStatusProps {
  readonly connection: ProvisionalDevice["connection"];
}

export function ConnectionStatus({ connection }: ConnectionStatusProps): ReactElement {
  const online = connection === "online";
  const label = online ? "Online" : "Offline";

  return (
    <span className={`connection-status connection-status--${connection}`}>
      <svg
        aria-label={`Indicador ${label.toLowerCase()}`}
        className="connection-status__icon"
        role="img"
        viewBox="0 0 16 16"
      >
        <circle cx="8" cy="8" fill="none" r="6.25" stroke="currentColor" strokeWidth="1.5" />
        {online ? (
          <path d="m5 8.1 1.8 1.8L11.3 5.7" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
        ) : (
          <path d="M8 4.6v4M8 11.2v.2" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" />
        )}
      </svg>
      <span>{label}</span>
    </span>
  );
}
