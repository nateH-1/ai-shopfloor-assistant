export async function get_role_permissions() {
    let response: Response;
    try {
        response = await fetch(`/roles/permissions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
        });  
    } catch {
        throw new Error("Unable to reach the backend server. Please try again.")
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || data?.error) {
        throw new Error(data?.error || "Authentication failed. Please try again.");
    }
    return data;
}