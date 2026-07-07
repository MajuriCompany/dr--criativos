import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, isValidSessionCookie } from "@/lib/auth";
import Dashboard from "@/components/Dashboard";

export default async function Home() {
  const store = await cookies();
  const value = store.get(SESSION_COOKIE)?.value;
  if (!isValidSessionCookie(value)) {
    redirect("/login");
  }
  return <Dashboard />;
}
