import { NextRequest, NextResponse } from "next/server";
import { getUserContext } from "@/app/lib/auth";
import { pendingCodes, cleanupExpiredCodes, CODE_TTL_MS } from "@/app/lib/desktop-auth-store";
import crypto from "crypto";

// Called by the browser tab the Python app opened, once the person is
// signed in. Mints a short-lived one-time code carrying their identity,
// which the Python app's local callback server redeems via
// /api/desktop-auth/exchange below.
export async function POST(req: NextRequest) {
  try {
    const ctx = await getUserContext();
    cleanupExpiredCodes();

    const code = crypto.randomBytes(24).toString("hex");
    pendingCodes.set(code, {
      userId: ctx.userId,
      orgId: ctx.orgId,
      expiresAt: Date.now() + CODE_TTL_MS,
    });

    return NextResponse.json({ code });
  } catch (err) {
    if (err instanceof Error && err.message === "Unauthenticated") {
      return NextResponse.json({ error: "Unauthenticated" }, { status: 401 });
    }
    console.error("desktop-auth/complete error:", err);
    return NextResponse.json({ error: "Failed to pair" }, { status: 500 });
  }
}