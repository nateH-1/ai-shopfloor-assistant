import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backend = (process.env.FLASK_URL ?? "http://localhost:5000").replace(/\/$/, "");
    return [
      { source: "/users/register", destination: `${backend}/users/register` },
      { source: "/users/login", destination: `${backend}/users/login` },
    ];
  },
};

export default nextConfig;

