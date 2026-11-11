import { tabFetch } from "./tabSession";
import { parseTheme, type Theme } from "./theme";
import { AuthenticationRequiredError } from "./authApi";

export type AccountTheme = {
  theme: Theme | null;
  user_id: string | null;
  login_id: string;
};

export async function getThemePreference(): Promise<AccountTheme> {
  const response = await tabFetch("/users/theme");
  const data = await response.json().catch(() => null);
  if (response.status === 401) throw new AuthenticationRequiredError();
  if (!response.ok) {
    throw new Error(data?.error || "Unable to load your theme preference.");
  }
  if (!data || (data.theme !== null && parseTheme(data.theme) === null)
      || (data.user_id !== null && (typeof data.user_id !== "string" || !data.user_id))
      || typeof data.login_id !== "string" || !data.login_id) {
    throw new Error("The server returned an invalid theme preference.");
  }
  return data;
}

export async function saveThemePreference(account: AccountTheme, theme: Theme): Promise<void> {
  const response = await tabFetch("/users/theme", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme, user_id: account.user_id, login_id: account.login_id }),
    // Keep the small save request alive when Settings or the document closes.
    keepalive: true,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || data?.theme !== theme) {
    throw new Error(data?.error || "Unable to save your theme preference. Please try again.");
  }
}
