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
        throw new Error(data?.error || `Failed to load role permissions (HTTP ${response.status}).`);
    }
    return data;
}

export async function get_users() {
    let response: Response;
    try {
        response = await fetch(`/users`, {
            method: "GET",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
        })
    } catch {
        throw new Error("Unable to reach the backend server. Please try again.")
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || data?.error) {
        throw new Error(data?.error || `Failed to load users (HTTP ${response.status}).`);
    }
    return data;
}

export async function verify_user(
    user_id: string,
    new_status: "VERIFIED" | "REJECTED"
) {
    let response: Response;
    try {
        response = await fetch(`/users/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
                user_id: user_id,
                verification_status: new_status
            })
        })
    } catch {
        throw new Error("Unable to reach the backend server. Please try again.")
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || data?.error) {
        throw new Error(data?.error || `Failed to update user verification (HTTP ${response.status}).`);
    }
    return get_users()
}

export async function delete_user(user_id: string): Promise<void> {
    let response: Response;
    try {
        response = await fetch("/users/delete", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ user_id }),
        });
    } catch {
        throw new Error("Unable to reach the backend server. Please try again.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || data?.error) {
        throw new Error(data?.error || `Failed to delete user (HTTP ${response.status}).`);
    }
}

export async function change_user_role(user_id: string, role: "Worker" | "Admin"): Promise<void> {
    let response: Response;
    try {
        response = await fetch("/users/change-role", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ user_id, role }),
        });
    } catch {
        throw new Error("Unable to reach the backend server. Please try again.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || data?.error) {
        throw new Error(data?.error || `Failed to change user role (HTTP ${response.status}).`);
    }
}
