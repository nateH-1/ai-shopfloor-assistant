"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header"
import UserManagementBubble from "@/components/UserManagementBubble";
import DocumentBubble from "@/components/DocumentBubble";
import { get_role_permissions } from "@/lib/settingsAPI";
import { get_verification_status } from "@/lib/authApi";


export default function Settings() {

    interface role_info {
        name: string,
        can_upload_files: boolean,
        files_get_saved: boolean,
        can_start_server: boolean,
        can_join_server: boolean,
        can_select_model: boolean,
        can_manage_users: boolean
    };

    const [roleInfo, setRoleInfo] = useState<role_info | null>(null);
    const [verificationStatus, setVerificationStatus] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;

        async function loadRoleInfo() {
            try {
                const verification = await get_verification_status();
                if (!active) return;
                if (!verification?.verification_status) {
                    throw new Error("Failed to load verification status.");
                }
                setVerificationStatus(verification.verification_status);
                if (verification.verification_status !== "VERIFIED") return;

                const data = await get_role_permissions();
                if (active) {
                    setRoleInfo(data);
                }
            } catch (error) {
                if (active) {
                    setError(error instanceof Error ? error.message : "Failed to load settings.");
                }
            }
        }

        void loadRoleInfo();

        return () => {
            active = false;
        };
    }, []);

    return (
        <div className="flex flex-col h-screen overflow-hidden">
          <Header showChat />
          <main className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-6 sm:space-y-8 sm:px-6 sm:py-8 lg:px-8">
          {error ? (
            <p role="alert" className="w-full rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-center text-sm font-medium leading-relaxed text-red-700">{error}</p>
          ) : verificationStatus === null ? (
            <p role="status" className="text-center text-sm text-gray-600">Checking verification status...</p>
          ) : verificationStatus !== "VERIFIED" ? (
            <p role="status" className="w-full rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-center text-sm font-medium leading-relaxed text-amber-800">Please wait for an admin to verify your account.</p>
          ) : !roleInfo ? (
            <p role="status" className="text-center text-sm text-gray-600">Loading permissions...</p>
          ) : null}
          {roleInfo?.can_manage_users ? (
            <UserManagementBubble/>
          ) : null}
          {roleInfo?.can_upload_files ? (
            <DocumentBubble/>
          ) : null}
            
          </main>
        </div>
      );


}
