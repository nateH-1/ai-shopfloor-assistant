"use client";

import { useState, useEffect } from "react"; 
import { change_user_role, delete_user, get_users, verify_user } from "@/lib/settingsAPI";
    
export default function UserManagementBubble() {

    interface user_info {
        id: string
        username: string,
        full_name: string,
        verification_status: "PENDING" | "VERIFIED" | "REJECTED"
        name: string
    };

    interface users_info {
        verified_users: user_info[],
        pending_users: user_info[]
    };

    const [users, setUsers] = useState<users_info | null>(null);
    const [loadingUsers, setLoadingUsers] = useState(true);
    const [error, setError] = useState("");
    const [onVerified, setOnVerified] = useState(false);
    const [saving, setSaving] = useState(false);
    const [actionError, setActionError] = useState("");

    async function handleRoleChange(userId: string, role: "Worker" | "Admin") {
        if (saving) return;
        setSaving(true);
        setActionError("");
        try {
            await change_user_role(userId, role);
            setUsers((current) => current ? {
                ...current,
                verified_users: current.verified_users.map((user) =>
                    user.id === userId ? { ...user, name: role } : user
                ),
            } : current);
        } catch (error) {
            setActionError(error instanceof Error ? error.message : "Failed to change user role.");
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete(userId: string) {
        if (saving) return;
        setSaving(true);
        setActionError("");
        try {
            await delete_user(userId);
            setUsers((current) => current ? {
                ...current,
                verified_users: current.verified_users.filter((user) => user.id !== userId),
            } : current);
        } catch (error) {
            setActionError(error instanceof Error ? error.message : "Failed to delete user.");
        } finally {
            setSaving(false);
        }
    }

    useEffect(() => {
        let active = true;

        async function loadUsers() {
            try {
                const data = await get_users();
                if (active) {
                    setUsers(data);
                }
            } catch (error) {
                if (active) {
                    setError(error instanceof Error ? error.message : "Failed to load users.");
                }
            } finally {
                if (active) {
                    setLoadingUsers(false);
                }
            }
        }
        void loadUsers();
        return () => {
            active = false;
        };
    }, []);

    return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-8">
      <h2 className="text-lg font-semibold text-[#1a202c]">Manage Users</h2>
      <div className="grid grid-cols-2 gap-3 sm:gap-4">
        {(["Pending Users", "Verified Users"] as const).map((option) => (
          <label key={option} className="cursor-pointer">
            <input
              type="radio"
              name="role"
              value={option}
              checked={onVerified === (option === "Verified Users")}
              disabled={saving}
              onChange={() => setOnVerified(option == "Verified Users" ? true : false)}
              className="peer sr-only"
            />
            <span className="block rounded-lg border-2 border-transparent px-3 py-2.5 text-center text-sm font-medium text-[#2d3748] transition-colors hover:bg-blue-50 peer-checked:border-blue-500 peer-checked:bg-blue-50 peer-checked:text-blue-700 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-blue-500">
              {option}
            </span>
          </label>
        ))}
      </div>

      {actionError && <p role="alert" className="text-sm text-red-600">{actionError}</p>}
      {saving && <p role="status" className="text-sm text-gray-600">Saving changes...</p>}

      {loadingUsers ? (
        <p className="mb-1.5 block text-sm font-medium text-[#2d3748]">Loading users...</p>
      ) : error ? (
        <p role="alert" className="text-sm text-red-600">{error}</p>
      ) : users?.verified_users.length && onVerified ? (
        <ul className="space-y-4">
          {users.verified_users.map((user) => (
            <li key={user.username} className="grid grid-cols-2 items-center gap-3 rounded-lg border border-gray-200 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_7rem_5rem] sm:gap-6 sm:p-5">
              <p title={user.full_name} className="min-w-0 truncate font-medium text-[#1a202c]">{user.full_name}</p>
              <p title={user.username} className="min-w-0 truncate text-sm text-gray-600">{user.username}</p>
              <select
                aria-label={`Role for ${user.username}`}
                value={user.name}
                disabled={saving}
                onChange={(event) => {
                  const role = event.target.value;
                  if (role === "Worker" || role === "Admin") {
                    void handleRoleChange(user.id, role);
                  }
                }}
                className="min-w-0 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:cursor-wait disabled:opacity-50"
              >
                {user.name !== "Guest" && user.name !== "Admin" && (
                  <option value={user.name} disabled>{user.name}</option>
                )}
                <option value="Guest">Guest</option>
                <option value="Admin">Admin</option>
              </select>
              <button
                type="button"
                disabled={saving}
                onClick={() => { void handleDelete(user.id); }}
                aria-label={`Delete ${user.username}`}
                className="justify-self-end rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      ) : users?.pending_users.length && !onVerified ? (
       <ul className="space-y-4">
          {users.pending_users.map((user) => (
            <li key={user.username} className="grid grid-cols-5 items-center gap-3 rounded-lg border border-gray-200 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_5rem_5rem] lg:gap-6">
              <p title={user.full_name} className="min-w-0 truncate font-medium text-[#1a202c]">{user.full_name}</p>
              <p title={user.username} className="min-w-0 truncate text-sm text-gray-600">{user.username}</p>
              <p title={user.name} className="min-w-0 truncate text-sm text-gray-600">{user.name}</p>
              <button className="rounded-lg bg-blue-50 px-2 py-2 text-sm font-medium text-blue-700 transition-colors hover:bg-blue-100" onClick={async () => {
                try {
                  const updatedUsers = await verify_user(user.id, "VERIFIED");
                  setUsers(updatedUsers);
                } catch (error) {
                  setError(error instanceof Error ? error.message : "Failed to verify user.");
                }
              }}>
                Verify
              </button>
              <button className="rounded-lg bg-red-50 px-2 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100" onClick={async () => {
                try {
                  const updatedUsers = await verify_user(user.id, "REJECTED");
                  setUsers(updatedUsers);
                } catch (error) {
                  setError(error instanceof Error ? error.message : "Failed to verify user.");
                }
              }}>
                Reject
              </button>
            </li>
          ))}
        </ul>
      ) : onVerified ? (
        <p className="text-sm text-gray-600">No verified users found.</p>
      ) : (
        <p className="text-sm text-gray-600">No pending users.</p>
      )}
    </div>
    );
}
