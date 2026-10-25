// Header component matching Figma design
// Blue header (#3B82F6) with robot icon on left, "Kuldeep" brand text on right,
// and optional settings and chat links.

import Link from "next/link";

interface HeaderProps {
  showSettings?: boolean;
  showChat?: boolean;
}

export default function Header({ showSettings, showChat }: HeaderProps) {
  return (
    <header
      className="w-full flex items-center justify-between px-5 py-3"
      style={{ backgroundColor: "#3B82F6" }}
    >
      {/* Left: Custom icon in white circle + navigation */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-full bg-white/20">
          <img src="/icon.png" alt="Kuldeep icon" className="w-6 h-6 object-contain" />
        </div>
        {showSettings && (
          <Link
            href="/settings"
            className="flex items-center gap-1.5 rounded-lg bg-white/15 hover:bg-white/25 transition-colors px-3 py-1.5"
            title="Open settings"
          >
            <SettingsIcon className="w-4 h-4 text-white" />
            <span className="text-white text-xs font-medium">Settings</span>
          </Link>
        )}
        {showChat && (
          <Link
            href="/chat"
            className="flex items-center gap-1.5 rounded-lg bg-white/15 hover:bg-white/25 transition-colors px-3 py-1.5"
            title="Back to chat"
          >
            <svg aria-hidden="true" className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m12 19-7-7 7-7M5 12h14" />
            </svg>
            <span className="text-white text-xs font-medium">Back to Chat</span>
          </Link>
        )}
      </div>

      {/* Right: Brand name */}
      <span
        className="text-white text-2xl tracking-widest select-none"
        style={{ fontFamily: "var(--font-cinzel), serif", fontWeight: 500 }}
      >
        Kuldeep
      </span>
    </header>
  );
}

function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m9 3-1 3-3 1-2 3 2 2-1 3 2 3 3-1 2 3h3l1-3 3-1 2-3-2-2 1-3-2-3-3 1-2-3Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function RobotIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Antenna */}
      <rect x="11" y="1" width="2" height="3" rx="1" />
      <circle cx="12" cy="1.5" r="1.5" />
      {/* Head */}
      <rect x="4" y="4" width="16" height="12" rx="3" />
      {/* Eyes */}
      <circle cx="9" cy="9" r="1.5" fill="currentColor" opacity="0.4" />
      <circle cx="15" cy="9" r="1.5" fill="currentColor" opacity="0.4" />
      <circle cx="9" cy="9" r="0.75" fill="white" />
      <circle cx="15" cy="9" r="0.75" fill="white" />
      {/* Mouth */}
      <rect x="8" y="12" width="8" height="1.5" rx="0.75" fill="white" opacity="0.7" />
      {/* Body */}
      <rect x="7" y="16" width="10" height="6" rx="2" />
      {/* Arms */}
      <rect x="2" y="17" width="4" height="4" rx="2" />
      <rect x="18" y="17" width="4" height="4" rx="2" />
    </svg>
  );
}
