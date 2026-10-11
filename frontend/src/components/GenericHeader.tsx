// Header component matching Figma design
// Blue header (#3B82F6) with centered branding and account buttons on the right.

"use client";

interface GenericHeaderProps {
  onLogIn: () => void;
  onSignUp: () => void;
}

export default function GenericHeader({ onLogIn, onSignUp }: GenericHeaderProps) {

  return (
    <header
      className="grid w-full grid-cols-1 items-center gap-y-3 px-5 py-3 sm:grid-cols-[1fr_auto_1fr]"
      style={{ backgroundColor: "#3B82F6" }}
    >
      {/* Center: Custom icon and brand name */}
      <div className="flex items-center justify-center gap-3 sm:col-start-2 sm:row-start-1">
        <div className="flex items-center justify-center w-9 h-9 rounded-full bg-white/20">
          <img src="/icon.png" alt="Kuldeep icon" className="w-6 h-6 object-contain" />
        </div>
        <span
          className="text-white text-2xl tracking-widest select-none"
          style={{ fontFamily: "var(--font-cinzel), serif", fontWeight: 500 }}
        >
          Kuldeep
        </span>
      </div>
      <div className="flex items-center justify-self-end gap-3 sm:col-start-3 sm:row-start-1">
        <button type="button" onClick={onLogIn} className="whitespace-nowrap rounded-lg bg-[#f3f4f6] px-4 py-2.5 text-sm font-medium text-black transition-colors hover:bg-[#c9c9c9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c9c9c9]">
          Log In
        </button>
        <button type="button" onClick={onSignUp} className="whitespace-nowrap rounded-lg bg-[#f3f4f6] px-4 py-2.5 text-sm font-medium text-black transition-colors hover:bg-[#c9c9c9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c9c9c9]">
          Sign Up
        </button>
      </div>
      
    </header>
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
