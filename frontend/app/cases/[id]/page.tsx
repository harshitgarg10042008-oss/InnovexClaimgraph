import { Suspense } from "react";
import WorkspaceClient from "./WorkspaceClient";
import { QueryProvider } from "../../components/QueryProvider";

export default function CasePage() {
  return (
    <Suspense fallback={<main className="page-shell"><p>Loading case...</p></main>}>
      <QueryProvider>
        <WorkspaceClient />
      </QueryProvider>
    </Suspense>
  );
}
