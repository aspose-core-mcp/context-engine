import { AdminSession } from "@/lib/admin-api";

export function hasScope(session: AdminSession, requiredScope: string): boolean {
  if (session.is_superuser) {
    return true;
  }
  return session.scopes.includes("*") || session.scopes.includes(requiredScope);
}
