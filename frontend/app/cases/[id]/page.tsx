import { Suspense } from "react";
import WorkspaceClient from "./WorkspaceClient";

export default function CasePage() {
  return <Suspense fallback={<main className="page-shell"><p>Loading case...</p></main>}><WorkspaceClient /></Suspense>;
}
