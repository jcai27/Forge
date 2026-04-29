import { CandidateAccessPanel } from "@/components/candidate-access-panel";
import { PageSection } from "@/components/ui";

export default function CandidateAccessPage() {
  return (
    <main className="page-stack">
      <PageSection>
        <CandidateAccessPanel />
      </PageSection>
    </main>
  );
}
