export type DevAuthRole = "candidate" | "reviewer" | "admin";

export const DEV_AUTH_HEADER = "X-Forge-Dev-Auth";

export function inferDevAuthRole(pathname?: string | null): DevAuthRole | null {
  if (!pathname) return null;
  if (pathname.startsWith("/candidate")) return "candidate";
  if (pathname.startsWith("/admin")) return "admin";
  if (pathname.startsWith("/login")) return "admin";
  return null;
}
