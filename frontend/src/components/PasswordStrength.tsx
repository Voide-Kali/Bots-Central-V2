import type { ReactElement } from "react";
import { passwordStrength } from "../app/passwordStrength";

// Animated strength meter for the password fields: four bars that fill and change colour as you
// type (red -> amber -> green), with a live label. Hidden until there is something to measure.
export function PasswordStrength({
  password,
  minLength = 15,
}: {
  readonly password: string;
  readonly minLength?: number;
}): ReactElement | null {
  const strength = passwordStrength(password, minLength);
  if (strength.score === 0) return null;

  const detail = strength.meets ? " — pode criar" : "";
  return (
    <div className="pw-strength" data-score={strength.score}>
      <div className="pw-strength__track" aria-hidden="true">
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={i <= strength.score ? "pw-strength__seg pw-strength__seg--on" : "pw-strength__seg"} />
        ))}
      </div>
      <p className="pw-strength__label" role="status" aria-live="polite">
        Força da senha: {strength.label}{detail}
      </p>
    </div>
  );
}
