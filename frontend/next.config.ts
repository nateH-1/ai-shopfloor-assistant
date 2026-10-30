import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backend = (process.env.FLASK_URL ?? "http://localhost:5000").replace(/\/$/, "");
    return [
      { source: "/users/session", destination: `${backend}/users/session` },
      { source: "/users/register", destination: `${backend}/users/register` },
      { source: "/users/login", destination: `${backend}/users/login` },
      { source: "/users/logout", destination: `${backend}/users/logout` },
      { source: "/roles/permissions", destination: `${backend}/roles/permissions` },
      { source: "/users", destination: `${backend}/users` },
      { source: "/users/verify", destination: `${backend}/users/verify` },
      { source: "/users/delete", destination: `${backend}/users/delete` },
      { source: "/users/change-role", destination: `${backend}/users/change-role` },
      { source: "/users/verification-status", destination: `${backend}/users/verification-status`},
    ];
  },
};

export default nextConfig;

