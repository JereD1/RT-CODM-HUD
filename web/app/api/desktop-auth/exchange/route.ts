import { NextRequest, NextResponse } from "next/server";
import { pendingCodes, cleanupExpiredCodes } from "@/app/lib/desktop-auth-store";

// Called by the Python app's local server — not a browser session, so
// this deliberately does NOT require Clerk auth. The one-time code itself
// is the credential (same shape as any device-authorization flow).
export async function POST(req: NextRequest) {
  try {
    const { code } = await req.json();
    if (!code || typeof code !== "string") {
      return NextResponse.json({ error: "Missing code" }, { status: 400 });
    }

    cleanupExpiredCodes();
    const entry = pendingCodes.get(code);
    if (!entry) {
      return NextResponse.json({ error: "Invalid or expired code" }, { status: 400 });
    }

    pendingCodes.delete(code); // one-time use

    return NextResponse.json({ userId: entry.userId, orgId: entry.orgId });
  } catch (err) {
    console.error("desktop-auth/exchange error:", err);
    return NextResponse.json({ error: "Failed to exchange code" }, { status: 500 });
  }
}