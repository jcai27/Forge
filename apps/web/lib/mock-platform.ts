export const trustLogos = ["Ramp", "Stripe", "Vercel", "Figma", "Linear", "OpenAI"];

export const featureHighlights = [
  {
    title: "Build once, share everywhere",
    description: "Candidates turn one serious project into a portable credential they can reuse across hiring processes.",
  },
  {
    title: "Real work in a premium build space",
    description: "Every project runs inside a controlled environment with code, checks, preview state, and milestones attached to the final artifact.",
  },
  {
    title: "Human-reviewed trust",
    description: "Projects become discoverable only after publication, so companies see signal they can trust instead of raw activity dumps.",
  },
  {
    title: "Discovery for both sides",
    description: "Candidates gain a public body of work, and hiring teams browse talent through projects, strengths, and proof of execution.",
  },
];

export const featuredProjects = [
  {
    id: "warehouse-ops-api-v1",
    title: "Warehouse Ops API",
    format: "Backend systems",
    fit: "Senior backend",
    duration: "4-5 hours",
    summary: "Design inventory adjustment flows, validation rules, and operationally safe behavior inside a real build environment.",
    skills: ["Python", "API design", "Validation", "Testing"],
  },
  {
    id: "growth-analytics-service-v1",
    title: "Growth Analytics Service",
    format: "Data product",
    fit: "Product engineer",
    duration: "3-4 hours",
    summary: "Ship a lightweight metrics pipeline and reporting surface that shows product judgment, code quality, and communication.",
    skills: ["TypeScript", "Analytics", "Product thinking", "SQL"],
  },
  {
    id: "checkout-reliability-ui-v1",
    title: "Checkout Reliability UI",
    format: "Full-stack experience",
    fit: "Frontend systems",
    duration: "4 hours",
    summary: "Build a resilient interface around an unstable payments flow and explain the tradeoffs you made under time pressure.",
    skills: ["React", "State design", "Reliability", "UX"],
  },
];

export const candidateStories = [
  {
    name: "Riley Chen",
    role: "Backend engineer",
    company: "Ramp",
    quote: "Forge let me show how I work, not just how I interview. The published project opened conversations that a resume never did.",
  },
  {
    name: "Jordan Kim",
    role: "Product engineer",
    company: "Stripe",
    quote: "I built one project with real ownership, then shared it with multiple companies instead of repeating the same take-home loop.",
  },
  {
    name: "Sam Okafor",
    role: "Full-stack engineer",
    company: "Vercel",
    quote: "The report felt more like a portfolio artifact than a scorecard. It actually captured my thinking and execution.",
  },
];

export const candidateAssignments = [
  {
    id: "warehouse-ops-api-v1",
    title: "Warehouse Ops API",
    company: "Ramp",
    role: "Backend Engineer",
    difficulty: "Senior",
    estimatedTime: "4-5 hours",
    deadline: "Apr 28, 2026",
    status: "active",
    score: null,
    reviewState: "building",
    description: "A production-minded backend build designed to showcase correctness, architecture, and communication.",
  },
  {
    id: "warehouse-ops-api-submitted",
    title: "Warehouse Ops API",
    company: "Stripe",
    role: "Product Engineer",
    difficulty: "Senior",
    estimatedTime: "5 hours",
    deadline: "Apr 19, 2026",
    status: "published",
    score: 84,
    reviewState: "published",
    description: "Published project with a reviewer summary, portable artifact, and employer-ready talking points.",
  },
  {
    id: "growth-analytics-service-v1",
    title: "Growth Analytics Service",
    company: "Linear",
    role: "Product Engineer",
    difficulty: "Senior",
    estimatedTime: "3-4 hours",
    deadline: "Apr 15, 2026",
    status: "published",
    score: 91,
    reviewState: "published",
    description: "Portable project showing product judgment and technical range across API, data, and reporting layers.",
  },
];

export const universalProject = {
  title: "Portable Project Portfolio",
  subtitle: "One profile, multiple published builds, reusable across hiring loops.",
  completion: 72,
  companiesUnlocked: 14,
  status: "Profile live",
};

export const assignmentChecklist = [
  "Read the take-home brief and confirm the success criteria.",
  "Inspect the starter repo before changing behavior.",
  "Implement the missing or incorrect API behavior.",
  "Run tests, add coverage where needed, and keep the suite green.",
  "Submit with a short note about one tradeoff you made.",
];

export const assignmentBrief = {
  id: "warehouse-ops-api-v1",
  title: "Warehouse Ops API",
  assignmentLabel: "Take-home assignment",
  roleFocus: "Backend engineer",
  expectedTime: "4-5 hours",
  starterRepo: "warehouse-ops-api-v1",
  overview:
    "You are joining a small logistics company that needs a reliable inventory adjustments API for warehouse operators and downstream reporting systems. Improve the seeded backend so the core behavior is correct, testable, and easy for a reviewer to trust.",
  framing:
    "This is a production-minded backend exercise. Reviewers are looking for sound engineering judgment under realistic constraints, not framework theatrics. A strong project credential fixes the important behavior, proves it with tests, and explains one tradeoff clearly.",
  primaryGoal: "Make the inventory adjustments API reliable enough that operators and downstream systems can trust it.",
  successBar: "Correct write behavior, safe validation, usable query responses, and a green test suite in the hosted environment.",
  whatMattersMost: "Correctness, stability, error handling, testing discipline, and a brief explanation of your tradeoffs.",
  projectFacts: [
    ["Assignment ID", "warehouse-ops-api-v1"],
    ["Role focus", "Backend engineer"],
    ["Expected time", "4-5 hours"],
    ["Starter repo", "warehouse-ops-api-v1"],
  ] as const,
  environmentFacts: [
    ["Environment", "Hosted workspace only"],
    ["Runtime", "Docker-backed managed session"],
    ["Allowed tools", "Editor, terminal, preview, checkpoints, AI assistant"],
    ["Submission includes", "Checks, timeline, AI usage summary, candidate reflection, reviewer rubric"],
  ] as const,
} as const;

export const assignmentTabs = [
  { id: "overview", label: "Overview" },
  { id: "requirements", label: "What to build" },
  { id: "rubric", label: "What companies learn" },
  { id: "resources", label: "References" },
  { id: "publish", label: "Publish" },
];

export const assignmentRequirements = [
  "Create and harden inventory adjustment write behavior so valid changes are recorded and invalid requests are rejected.",
  "Prevent duplicate or conflicting adjustments with clear validation, stable semantics, and useful error responses.",
  "Expose query behavior that lets warehouse operators and downstream systems inspect history by warehouse and SKU.",
  "Keep the tests green, add coverage where the starter repo is weak, and document one tradeoff you made under time pressure.",
];

export const assignmentDeliverables = [
  "Working code in the provided hosted workspace.",
  "A green test run in the managed environment.",
  "At least one added or improved test that covers a bug, gap, or edge case you addressed.",
  "A short written explanation of one design tradeoff or follow-up you would make with more time.",
];

export const assignmentGuardrails = [
  "Use the hosted workspace only. The exercise is designed to be completed inside the provided environment.",
  "AI assistance is allowed, but use it transparently. The published artifact summarizes AI usage and timeline context.",
  "Network egress is restricted, so prefer the provided code, tests, and local tooling instead of external dependencies.",
  "Optimize for correctness, clarity, and operational safety before adding polish or speculative extra features.",
];

export const assignmentWorkflow = [
  {
    title: "Read the seeded code first",
    detail: "Start by understanding the current routes, models, and tests so you can identify the gaps before editing.",
  },
  {
    title: "Fix the core API behavior",
    detail: "Prioritize invalid adjustment handling, duplicate prevention, and the warehouse or SKU history flows the prompt depends on.",
  },
  {
    title: "Prove the behavior with tests",
    detail: "Use the existing suite as a guide, then add or strengthen coverage where the starter implementation is weak.",
  },
  {
    title: "Capture your tradeoff clearly",
    detail: "Leave a concise note about one decision you made under time pressure and what you would improve next.",
  },
];

export const canonicalAssignmentBrief = {
  ...assignmentBrief,
  checklist: assignmentChecklist,
  requirements: assignmentRequirements,
  deliverables: assignmentDeliverables,
  guardrails: assignmentGuardrails,
  workflow: assignmentWorkflow,
} as const;

export const rubricDimensions = [
  { label: "Product thinking", weight: "15%", description: "Makes implementation choices that reflect user workflow, tradeoffs, and operational clarity." },
  { label: "Code quality", weight: "20%", description: "Readable, maintainable, and coherent code with strong naming and boundaries." },
  { label: "Correctness", weight: "20%", description: "Core behavior works, checks pass, and semantics stay dependable." },
  { label: "Architecture", weight: "15%", description: "Good extensibility decisions with sound runtime awareness." },
  { label: "Communication", weight: "15%", description: "Explains tradeoffs and future work clearly enough for a hiring manager to understand." },
  { label: "Execution", weight: "15%", description: "Delivers a project that feels intentional, not half-finished." },
];

export const previewMetrics = [
  { label: "Checks passing", value: "14 / 14", tone: "success" },
  { label: "Usability confidence", value: "High", tone: "accent" },
  { label: "Performance posture", value: "Healthy", tone: "warning" },
  { label: "Published bundle", value: "146 kB", tone: "neutral" },
];

export const reviewCategories = [
  { label: "Product thinking", score: 88 },
  { label: "Code quality", score: 91 },
  { label: "Execution", score: 79 },
  { label: "Correctness", score: 93 },
  { label: "Architecture", score: 86 },
  { label: "Communication", score: 84 },
];

export const reviewerCandidates = [
  { name: "Riley Chen", submission: "sub_7ef98d3fe9f3", company: "Ramp", reviewer: "Maya Patel", score: 87, status: "published", submittedAt: "Apr 23, 2026 • 11:08 AM" },
  { name: "Jordan Kim", submission: "sub_747998bbfb27", company: "Stripe", reviewer: "Alex Rivera", score: 83, status: "in_review", submittedAt: "Apr 23, 2026 • 9:24 AM" },
  { name: "Sam Okafor", submission: "sub_a421f7e0d1ab", company: "Vercel", reviewer: "Maya Patel", score: 91, status: "published", submittedAt: "Apr 22, 2026 • 6:42 PM" },
];

export const pricingTiers = [
  { name: "Talent Marketplace Pilot", price: "$4k / month", description: "One standardized project track, publication workflow, and employer discovery surface." },
  { name: "Hiring Infrastructure", price: "Custom", description: "Expanded discovery, benchmark governance, reviewer operations, and deployment support." },
];

export const runtimeSnapshots = [
  { label: "Build backend", value: "docker" },
  { label: "Preview backend", value: "docker" },
  { label: "Worker loop", value: "running" },
  { label: "Queued jobs", value: "3" },
];

export const portfolioProfile = {
  name: "Riley Chen",
  role: "Backend engineer",
  location: "New York, NY",
  headline: "Builds reliable product systems with a bias toward clarity, shipping speed, and operational safety.",
  summary:
    "Riley uses standardized projects as a living portfolio: each build is versioned, published with reviewer context, and reusable across hiring conversations.",
  shareLink: "forge.dev/riley-chen",
  skills: ["Python", "FastAPI", "Product systems", "API design", "Testing", "Operational design"],
  strengths: ["Clear architecture under time pressure", "High-signal debugging habits", "Thoughtful product tradeoffs"],
  featuredProject: {
    title: "Warehouse Ops API",
    companyInterest: "Saved by 14 teams",
    summary: "A backend project focused on inventory adjustments, correctness, and operational clarity in a constrained build environment.",
    projectState: "Published with reviewer notes",
  },
  timeline: [
    { label: "Published Warehouse Ops API", detail: "Portable credential shared with 14 companies", date: "Apr 23" },
    { label: "Completed Growth Analytics Service", detail: "Second published build with strong product signals", date: "Apr 15" },
    { label: "Profile opened to discovery", detail: "Portfolio became searchable to partner companies", date: "Apr 04" },
  ],
  comparisonInsights: [
    "Strong correctness and architecture signals relative to the current backend cohort.",
    "Hiring teams most often shortlist this profile for backend and product-platform roles.",
    "Published artifacts outperform resumes alone when teams want tangible evidence quickly.",
  ],
};

export const discoveryFilters = ["Backend", "Frontend", "Product engineer", "API design", "Systems", "Published this month"];

export const discoverCandidates = [
  {
    name: "Riley Chen",
    role: "Backend engineer",
    location: "New York",
    headline: "Turns messy product constraints into clear, reliable systems.",
    featuredProject: "Warehouse Ops API",
    projectSummary: "Inventory adjustments, validation, and testing discipline in a production-minded API build.",
    skills: ["Python", "FastAPI", "Testing"],
    signal: "High trust",
    shareLink: "forge.dev/riley-chen",
  },
  {
    name: "Jordan Kim",
    role: "Product engineer",
    location: "San Francisco",
    headline: "Blends product judgment with disciplined backend execution.",
    featuredProject: "Growth Analytics Service",
    projectSummary: "Shipped a data-backed reporting build with thoughtful API boundaries and clear explanation quality.",
    skills: ["TypeScript", "SQL", "Product thinking"],
    signal: "Published",
    shareLink: "forge.dev/jordan-kim",
  },
  {
    name: "Sam Okafor",
    role: "Full-stack engineer",
    location: "London",
    headline: "Comfortable across interface polish, reliability, and systems thinking.",
    featuredProject: "Checkout Reliability UI",
    projectSummary: "Improved a failure-prone checkout experience with clear fallback behavior and strong delivery polish.",
    skills: ["React", "Reliability", "UX systems"],
    signal: "Fast mover",
    shareLink: "forge.dev/sam-okafor",
  },
];
