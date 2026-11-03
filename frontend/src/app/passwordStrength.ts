// Password strength, tuned to the Aval policy: a long passphrase (>= minLength) beats symbol
// soup (NIST 800-63B). Length drives the score; character variety only nudges a passing password
// from "boa" to "forte". Below the minimum it is always weak, no matter how fancy — the server
// rejects it anyway.

export interface PasswordStrength {
  // 0 = empty, 1-2 = below the minimum (weak), 3 = meets the minimum, 4 = comfortably strong.
  readonly score: 0 | 1 | 2 | 3 | 4;
  readonly label: string;
  readonly meets: boolean;
  readonly remaining: number; // characters still missing to reach minLength (0 once met)
}

export function passwordStrength(password: string, minLength = 15): PasswordStrength {
  const length = password.length;
  if (length === 0) return { score: 0, label: "", meets: false, remaining: minLength };

  const remaining = Math.max(0, minLength - length);
  if (remaining > 0) {
    const score = length < minLength / 2 ? 1 : 2;
    return { score, label: score === 1 ? "Muito fraca" : "Fraca", meets: false, remaining };
  }

  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  const extra = length - minLength;
  const strong = extra >= 6 || variety >= 3;
  return {
    score: strong ? 4 : 3,
    label: strong ? "Forte" : "Boa",
    meets: true,
    remaining: 0,
  };
}
