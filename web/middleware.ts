import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, isValidSessionCookie } from "./lib/auth";

// Every route except /login and /api/login requires the shared-password
// session cookie. Comparison is done directly against APP_PASSWORD (no
// signing library) — acceptable for a small trusted team behind one shared
// login; see lib/auth.ts for the reasoning.
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (pathname === "/login" || pathname === "/api/login") {
    return NextResponse.next();
  }

  const cookie = req.cookies.get(SESSION_COOKIE)?.value;
  if (!isValidSessionCookie(cookie)) {
    const loginUrl = req.nextUrl.clone();
    loginUrl.pathname = "/login";
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
