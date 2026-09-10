import { ApiError, ApiUnavailableError } from "../api";
export function apiMessage(error: unknown): string {
  if (error instanceof ApiUnavailableError) return "A API está indisponível no momento. Tente novamente em alguns instantes.";
  if (error instanceof ApiError) return "Não foi possível concluir a solicitação. Revise os dados e tente novamente.";
  return "Não foi possível concluir a solicitação agora. Tente novamente.";
}
