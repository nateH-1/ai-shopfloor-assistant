export async function logout(): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/users/logout", {
      method: "POST",
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Unable to reach the server. Please try again.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.error || "Failed to log out. Please try again.");
  }
}

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


export class AuthenticationRequiredError extends Error {
  constructor() {
    super("Please log in.");
    this.name = "AuthenticationRequiredError";
  }
}

export async function get_verification_status(): Promise<{
  verification_status: "PENDING" | "VERIFIED" | "REJECTED";
}> {
  let response: Response;
  try {
    response = await fetch("/users/verification-status", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      cache: "no-store",
      });
  } catch {
    throw new Error("Unable to reach the backend server. Please try again.");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401) {
    throw new AuthenticationRequiredError();
  }
  if (!response.ok || data?.error) {
    throw new Error(data?.error || `Failed to load verification status (HTTP ${response.status}).`);
  }
  if (!["PENDING", "VERIFIED", "REJECTED"].includes(data?.verification_status)) {
    throw new Error("The server returned an invalid verification status.");
  }
  return data;
}
