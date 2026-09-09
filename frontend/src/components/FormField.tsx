import type { InputHTMLAttributes, ReactElement } from "react";
interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> { readonly id: string; readonly label: string; readonly hint?: string; }
export function FormField({ id, label, hint, ...inputProps }: FormFieldProps): ReactElement {
  const hintId = hint === undefined ? undefined : `${id}-hint`;
  return <div className="form-field"><label htmlFor={id}>{label}</label><input id={id} aria-describedby={hintId} {...inputProps} />{hint === undefined ? null : <p id={hintId}>{hint}</p>}</div>;
}
