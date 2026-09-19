import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTheme } from "../lib/theme";

function Wordmark() {
  return (
    <Link
      to="/"
      className="flex items-center gap-2 text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100"
    >
      <svg
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 2.5 19.5 9 12 21.5 4.5 9 12 2.5Z" />
        <path d="M4.5 9h15M12 2.5 9 9l3 12.5L15 9l-3-6.5" />
      </svg>
      CrystalPilot
    </Link>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      aria-label="Toggle color theme"
      className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 transition-colors duration-150 hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
    >
      {theme === "dark" ? (
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
        </svg>
      )}
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-dvh flex-col bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-200 px-5 dark:border-zinc-800">
        <Wordmark />
        <ThemeToggle />
      </header>
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  );
}
