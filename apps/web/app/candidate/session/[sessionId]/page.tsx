import { WorkspaceShell } from "@/components/workspace-shell";

export default async function CandidateSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return <WorkspaceShell sessionId={sessionId} />;
}
