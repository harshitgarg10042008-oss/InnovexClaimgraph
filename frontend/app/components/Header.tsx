"use client";

import Link from "next/link";
import { Circle, Plus } from "lucide-react";

export function Header() {
  return (
    <header className="app-header">
      <Link href="/" className="brand">
        <span>ClaimGraph</span>
        <small>Evidence compiler</small>
      </Link>
      <nav aria-label="Primary">
        <Link href="/cases/new" className="button button-dark">
          <Plus size={16} aria-hidden="true" /> New case
        </Link>
        <Link href="/status" className="health-link">
          <Circle size={10} fill="currentColor" aria-hidden="true" /> System status
        </Link>
      </nav>
    </header>
  );
}
