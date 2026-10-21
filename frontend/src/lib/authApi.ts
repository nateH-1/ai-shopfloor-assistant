export async function authenticate(
  action: "register" | "login",
  info: { email: string; password: string; role: string; full_name?: string },
) {
  let response: Response;
  try {
    response = await fetch(`/users/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        username: info.email,
        password: info.password,
        role: info.role,
        ...(action === "register" ? { full_name: info.full_name?.trim() } : {}),
      }),
    });
  } catch {
    throw new Error("Unable to reach the server. Please try again.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok || data?.error || !data?.user_id) {
    throw new Error(data?.error || "Authentication failed. Please try again.");
  }
}
