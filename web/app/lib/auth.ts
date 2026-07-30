// lib/auth.ts
import { auth, currentUser } from "@clerk/nextjs/server";

export type Role = "free" | "pro" | "team" | "admin";
export const DEFAULT_ROLE: Role = "free";

export async function getUserRole(): Promise<Role> {
  const user = await currentUser();
  const role = user?.publicMetadata?.role as Role | undefined;
  return role ?? DEFAULT_ROLE;
}

export async function requireUserId(): Promise<string> {
  const { userId } = await auth();
  if (!userId) throw new Error("Unauthenticated");
  return userId;
}

/** Active Clerk org context for the current request, if any. orgId/orgRole/
 *  orgSlug come straight off the session — same org useOrganization() sees
 *  client-side, i.e. whichever org the user last set active. */
export interface UserContext {
  userId: string;
  orgId: string | null;
  orgRole: string | null;
  orgSlug: string | null;
}

export async function getUserContext(): Promise<UserContext> {
  const { userId, orgId, orgRole, orgSlug } = await auth();
  if (!userId) throw new Error("Unauthenticated");
  return {
    userId,
    orgId: orgId ?? null,
    orgRole: orgRole ?? null,
    orgSlug: orgSlug ?? null,
  };
}

/** Real-time channel scope for a feature. Team mode is an explicit opt-in
 *  (sent up from the client toggle) rather than "has an active org" —
 *  someone can belong to a team and still want to work solo on a controller.
 *  Keeps the non-team-mode value identical to a plain userId, so channel
 *  names don't shift depending on ambient Clerk state. */
export function getScopeId(ctx: UserContext, teamMode: boolean): string {
  if (teamMode && ctx.orgId) return `org-${ctx.orgId}`;
  return ctx.userId;
}