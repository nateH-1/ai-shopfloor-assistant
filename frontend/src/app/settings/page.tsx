"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header"
import { get_role_permissions } from "@/lib/settingsAPI";


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
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let active = true;

        async function loadRoleInfo() {
            try {
                const data = await get_role_permissions();
                if (active) {
                    setRoleInfo(data);
                }
            } catch (error) {
                if (active) {
                    setError(error instanceof Error ? error.message : "Failed to load permissions.");
                }
            }
        }

        void loadRoleInfo();

        return () => {
            active = false;
        };
    }, []);

    if (error) return <p role="alert">{error}</p>;
    if (!roleInfo) return <p role="status">Loading permissions...</p>;

    return (
        <div className="flex flex-col h-screen overflow-hidden">
          <Header/>
          
        </div>
      );


}
