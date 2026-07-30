"use client";
import React, { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useUser, RedirectToSignIn } from "@clerk/nextjs";

function DesktopAuthInner() {
  const searchParams = useSearchParams();
  const port = searchParams.get("port");
  const { isSignedIn, isLoaded } = useUser();
  const [status, setStatus] = useState<"waiting" | "pairing" | "done" | "error">("waiting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !port) return;
    let cancelled = false;
    setStatus("pairing");
    fetch("/api/desktop-auth/complete", { method: "POST" })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: { code: string }) => {
        if (cancelled) return;
        setStatus("done");
        // Hand the one-time code to the Python app's local callback server.
        window.location.href = `http://127.0.0.1:${port}/callback?code=${encodeURIComponent(data.code)}`;
      })
      .catch(() => {
        if (cancelled) return;
        setError("Couldn't pair with Health Capture. Close this tab and try again from the app.");
        setStatus("error");
      });
    return () => { cancelled = true; };
  }, [isLoaded, isSignedIn, port]);

  if (!port) {
    return (
      <div className="min-h-screen bg-zinc-950 text-white flex items-center justify-center">
        <p className="text-red-400 text-sm">Missing ?port= — open this page from the Health Capture app, not directly.</p>
      </div>
    );
  }

  if (isLoaded && !isSignedIn) {
    // Clerk bounces back here (with the same ?port=) after sign-in.
    return <RedirectToSignIn redirectUrl={`/desktop-auth?port=${port}`} />;
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-white flex items-center justify-center">
      <div className="text-center space-y-2">
        <p className="text-sm text-zinc-400">
          {status === "waiting" && "Loading…"}
          {status === "pairing" && "Connecting Health Capture…"}
          {status === "done" && "Connected — you can close this tab."}
        </p>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>
    </div>
  );
}

export default function DesktopAuthPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-zinc-950" />}>
      <DesktopAuthInner />
    </Suspense>
  );
}