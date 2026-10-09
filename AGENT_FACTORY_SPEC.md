# MISSION: BUILD AN AUTONOMOUS AI AGENT FACTORY

You are the principal engineer, AI systems architect, and product designer responsible for building a complete, production-oriented full-stack application called **Agent Factory**.

Your job is to IMPLEMENT THE APPLICATION, not merely propose an architecture, generate mockups, or scaffold empty routes.

Treat this as a long-horizon engineering task. You are expected to plan, implement, execute, test, debug, and iterate across multiple stages until there is a working end-to-end product.

Do not stop at the first functioning prototype. Continue until the core acceptance criteria have been met and verified.

## 1. PRODUCT VISION

Build a general-purpose platform that autonomously constructs specialized AI agents for real business operations.

A user should be able to provide a natural-language request such as:

"Build me an agent that processes restaurant orders received by email, matches products to our SKU catalog, checks inventory and customer pricing, creates orders in our ERP, and asks for approval when uncertain."

Or:

"Build an agent that receives RFQs, looks up our supplier prices, applies customer-specific margins, and creates accurate customer quotes."

Or:

"Build an agent that coordinates interview scheduling, tracks candidates, and updates our hiring system."

The platform must transform these requests into deployable agents that can access connected business systems, understand domain-specific data, execute workflows, and operate under configurable safeguards.

Most importantly, the platform must be capable of IMPROVING the agents it builds through repeated evaluation.

The central product loop is:

1. Understand the business task.
2. Discover available integrations and data.
3. Design a specialized agent.
4. Construct its tools, instructions, schemas, and workflow.
5. Generate or import representative test scenarios.
6. Run the agent against those scenarios.
7. Capture structured execution traces.
8. Evaluate accuracy, correctness, reliability, cost, and latency.
9. Identify specific failure modes.
10. Propose and implement improvements.
11. Rerun regression tests.
12. Compare the new candidate against the previous best version.
13. Repeat within a configurable iteration and cost budget.
14. Deliver the best verified agent for user review and deployment.

This loop is the HEART of the application. Prioritize it over peripheral features.

## 2. CORE PRINCIPLES

- Build working vertical slices, not disconnected components.
- Actual agent execution must use a real agent runtime.
- Agents must be defined through versioned, structured configurations.
- The builder must support agent improvement through measurable testing, not unverified self-critique.
- All agent executions must be observable and reproducible where practical.
- Real-world data can be used for authorized evaluation, but side effects must be isolated.
- Never execute destructive or external business actions during testing without explicit authorization.
- Never expose integration credentials to models or frontend clients.
- Prefer deterministic tools and business logic over LLM reasoning where possible.
- The product must be extensible across industries, not hardcoded to restaurants.
- Do not conflate an agent's confidence with its actual correctness.
- An improved prompt is not evidence of an improved agent until evaluation results verify the improvement.
- Build for real deployment with meaningful security, not just a local demo.

## 3. TECHNOLOGY STACK

Use the following default stack unless you identify a compelling technical reason to change it.

Frontend:
- Next.js with App Router
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- React Flow for workflow/agent visualization
- Recharts for evaluation metrics
- Server-Sent Events or WebSockets for live build and execution progress

Backend:
- Python
- FastAPI
- Pydantic
- OpenAI Agents SDK (Python)
- SQLAlchemy
- PostgreSQL
- Redis
- A durable background workflow system such as Temporal, or a well-designed equivalent with persistent resumability
- pgvector if semantic retrieval is actually needed
- Docker Compose for local services

Tooling:
- uv or equivalent Python package management
- pnpm for the frontend
- Alembic for migrations
- Pytest for backend tests
- Vitest and Playwright for frontend and end-to-end tests
- Ruff and TypeScript strict checks

Use the current official OpenAI Agents SDK documentation. Verify installed SDK APIs before implementing them. Do not invent SDK capabilities or depend on obsolete methods.

Prefer a monorepo:

/apps/web
/apps/api
/packages/contracts
/services/worker
/integrations
/tests
/docs
/docker-compose.yml
/README.md
/AGENTS.md
/PLANS.md

You may improve the directory structure when justified.

## 4. UX: MAIN PRODUCT EXPERIENCE

Create a polished SaaS interface resembling an AI-native developer platform.

It must feel like a usable product, not a hackathon demo.

### A. Dashboard

Display:
- Existing agents
- Build status
- Deployed agents
- Recent runs
- Evaluation scores
- Failure rates
- Cost and latency
- Pending human approvals

Provide obvious actions to create, inspect, test, and deploy agents.

### B. Agent Creation Workspace

The user provides a natural-language description of the business process.

The interface should resemble a conversational agent-building environment with a persistent project workspace.

The builder must ask clarifying questions ONLY when necessary to resolve genuinely ambiguous requirements.

It should infer reasonable defaults otherwise.

Display the builder's current stage, plan, tool calls, generated configuration, test results, and improvement decisions.

Allow users to stop, resume, or redirect an in-progress build.

### C. Integration Workspace

Users should be able to:
- Connect supported third-party systems.
- Inspect available data sources.
- View schemas and sample records.
- Select resources available to an agent.
- Configure read/write permissions.
- Test integration connections.
- See which tools each integration provides.
- Revoke access.

### D. Agent Studio

For each generated agent, display:
- Agent name and purpose
- Current version
- Instructions
- Tools
- Connected integrations
- Input/output schemas
- Workflow visualization
- Execution history
- Evaluation results
- Guardrails and approval rules
- Deployment status

Allow controlled manual editing and retesting of agent configurations.

### E. Evaluation Lab

This should be one of the richest parts of the product.

Show:
- Test scenarios
- Expected behavior
- Actual results
- Tool calls
- Execution traces
- Failure classifications
- Accuracy and reliability metrics
- Latency and token/cost metrics
- Version comparisons
- Regression history

Users should be able to inspect why an agent failed and what the builder changed in response.

### F. Deployment Console

Allow users to:
- Deploy an approved agent version.
- Invoke it manually.
- Invoke it via authenticated API.
- Configure webhooks or schedules.
- Set approval policies.
- Monitor production execution.
- Pause or disable an agent.
- Roll back to an earlier version.

## 5. AGENT FACTORY ARCHITECTURE

Implement the factory as a coordinated system of specialized roles, using the OpenAI Agents SDK where appropriate.

Suggested roles:

### Requirements Analyst

Converts user requests into a structured business specification.

Produces:
- Business objective
- Input data
- Expected outputs
- Required systems
- Workflow steps
- Business rules
- Exceptions
- Success metrics
- Side-effect permissions

### Integration Analyst

Examines connected systems.

Determines:
- Available tools
- Relevant database tables and APIs
- Authentication scopes
- Data relationships
- Constraints
- Missing integrations

Do not let this agent invent nonexistent APIs.

### Agent Architect

Designs the specialized agent.

Produces a versioned AgentSpec containing:
- Identity and purpose
- Instructions
- Input/output schemas
- Tools
- Model configuration
- Workflow design
- Guardrails
- Approval policies
- Error handling
- Success criteria

### Agent Builder

Converts the AgentSpec into an executable agent using the Agents SDK.

Build dynamically from configuration instead of generating and executing arbitrary Python source code.

If custom executable code is necessary, it must go through isolated build, validation, security review, and explicit promotion steps. Never execute unchecked model-generated code in the main application process.

### Test Designer

Creates evaluation cases from:
- User-provided examples
- Sanitized business records
- Documented business rules
- Edge cases
- Historical failures
- Synthetic fixtures

Distinguish between synthetic tests, replay tests, and authorized live read-only checks.

### Evaluation Agent

Evaluates agent behavior using deterministic assertions wherever possible.

Use model-based grading only when appropriate, with explicit rubrics and recorded evidence.

### Failure Analyst

Inspects failed traces and identifies likely root causes.

Examples:
- Wrong tool selected
- SKU mismatch
- Invalid output schema
- Incorrect business rule
- Missing information
- Incorrect arithmetic
- Unnecessary tool invocation
- Unauthorized side effect
- Missing human approval

### Optimization Agent

Proposes targeted changes to:
- Instructions
- Tool descriptions
- Retrieval settings
- Tool configuration
- Workflow structure
- Validation rules
- Exception handling
- Model selection

Changes must be versioned and evaluated.

### Deployment Reviewer

Determines whether the candidate meets configured quality gates.

The system may automatically mark a candidate ready for review, but production deployment requires an authorized user action unless an explicit deployment policy allows otherwise.

## 6. THE AUTONOMOUS IMPROVEMENT ENGINE

This is the most important technical requirement.

Build a persistent improvement workflow that can execute without maintaining an active browser session.

Its state machine should support:

DRAFT
→ DISCOVERING
→ DESIGNING
→ BUILDING
→ TESTING
→ ANALYZING
→ OPTIMIZING
→ RETESTING
→ READY_FOR_REVIEW
→ DEPLOYED

Also support PAUSED, WAITING_FOR_APPROVAL, FAILED, CANCELLED, and BUDGET_EXHAUSTED.

Each iteration should:

A. Select a candidate agent configuration.

B. Execute a suite of evaluations against isolated environments.

C. Collect structured traces, including:
- Input
- Output
- Tool calls
- Tool arguments, appropriately redacted
- Tool responses, appropriately redacted
- Duration
- Token usage
- Cost
- Errors
- Validation outcomes

D. Compute an evaluation scorecard.

Include:
- Task completion
- Exact-match or structured-field accuracy where applicable
- Business-rule compliance
- Tool correctness
- Safety violations
- Approval compliance
- Latency
- Cost
- Regression failures

E. Produce an evidence-based failure analysis.

F. Generate a targeted improvement hypothesis.

G. Create a NEW immutable candidate version.

H. Test the new candidate against development cases and a separate regression suite.

I. Promote the candidate to best-known version only if quality gates pass and performance improves according to the configured objective.

J. Continue until stopping conditions are met.

Stopping conditions:
- Target score achieved
- Maximum iterations reached
- Maximum cost reached
- Maximum elapsed time reached
- No measurable improvement across N iterations
- Critical unresolved failure
- User cancellation

Implement defaults such as:
- 10 maximum improvement iterations
- Configurable evaluation budget
- Configurable quality thresholds
- Early stopping after repeated non-improvement

All defaults must be editable.

Important: implement the loop as executable application logic, not as a prompt telling an LLM to "keep improving."

The loop must survive worker restarts.

Persist checkpoints, candidate versions, iteration outcomes, and event histories.

The frontend must show live progress, and users must be able to resume after reconnecting.

## 7. EVALUATION CORRECTNESS

Avoid self-confirming evaluation.

Use a separation between:
- Training/development examples
- Regression examples
- Held-out validation examples

The optimization agent must not receive hidden validation answers.

Do not promote candidates solely because an LLM says they are better.

Compare measurable results.

Provide support for:
- Deterministic assertions
- JSON schema validation
- Expected database state changes in test environments
- Tool-call sequence checks where appropriate
- Business invariants
- Model-graded qualitative assessments
- Human-reviewed examples

Track uncertainty and evaluator limitations.

If there is insufficient evidence to claim a high success rate, present the result as provisional.

For nondeterministic tests, support repeated trials and report variability.

Do not claim that an agent achieves 100% accuracy merely because it passes a small generated test set.

## 8. INTEGRATION FRAMEWORK

Build a reusable integration interface.

Each integration should expose:
- Identity
- Authentication mechanism
- Permissions
- Resource discovery
- Typed tool definitions
- Connection validation
- Input/output schemas
- Error handling
- Rate-limit handling
- Mock and replay capability
- Read/write classifications

Support the following initial connectors:

1. Generic REST API connector
2. PostgreSQL connector
3. CSV/XLSX file connector
4. Webhook connector
5. Email integration abstraction with a working provider adapter where credentials are available
6. MCP tool-server connector if supported by the installed SDK

Implement functioning connectors, not UI-only placeholders.

For OAuth-based providers, establish the actual authorization flow when feasible. If credentials or app registrations are unavailable, provide an explicit setup state and testable mock adapter rather than pretend the integration is connected.

Handle credential encryption, tenant scoping, connection revocation, and secret redaction.

Agent tools must be generated from approved integration schemas with least-privilege permissions.

## 9. DEMONSTRATION VERTICAL SLICES

Implement THREE specialized agent templates sharing the same underlying factory architecture.

### Template A: Restaurant Order Entry

Data:
- Incoming customer email
- Product catalog
- Customer catalog
- Customer-specific prices
- Available inventory
- Orders database

Behavior:
1. Parse an incoming order.
2. Identify customer.
3. Extract requested products and quantities.
4. Match requested products to catalog SKUs.
5. Resolve units of measure.
6. Check pricing and inventory.
7. Produce a structured order.
8. Flag ambiguous items.
9. Request approval when required.
10. Create the order in the test ERP only after approval.

Include edge cases:
- Misspelled items
- Customer-specific product aliases
- Duplicate products
- Ambiguous units
- Missing SKUs
- Insufficient stock
- Partial orders
- Duplicate incoming requests

### Template B: Quote Generation

Data:
- Supplier prices
- Customer records
- Product catalog
- Margin rules
- Historical quotes

Behavior:
1. Parse RFQ.
2. Identify requested products.
3. Retrieve supplier pricing.
4. Apply deterministic business pricing rules.
5. Generate quote lines.
6. Verify arithmetic.
7. Flag missing pricing.
8. Request approval where necessary.
9. Generate a structured quote.

### Template C: Hiring Operations

Data:
- Candidates
- Job openings
- Interview stages
- Interviewer availability fixtures
- Candidate communications

Behavior:
1. Interpret hiring operations requests.
2. Retrieve candidate and job information.
3. Identify next operational action.
4. Prepare scheduling or follow-up actions.
5. Request authorization before sending communications.
6. Update recruiting records in test environments.
7. Log decisions and outcomes.

Do not implement automatic discriminatory screening or unsupported employment decisions. Keep the workflow focused on administrative coordination.

These templates must demonstrate that the factory can build agents from reusable abstractions rather than from three separate hardcoded implementations.

## 10. DATA AND TESTING INFRASTRUCTURE

Provide seeded, realistic fictional business data.

For the order entry example, create:
- At least 100 products
- Multiple customers
- Customer-specific aliases
- Pricing variations
- Inventory records
- Historical sample orders
- At least 30 meaningful evaluation scenarios

Provide enough data to expose genuine failures and exercise the optimization loop.

Use local simulated business systems so evaluation runs are completely safe and reproducible.

Allow authorized imported real data to be mapped into the evaluation system.

Real data must be minimized, permission-scoped, and protected from accidental disclosure.

Imported data should not automatically become model-visible.

Build a mechanism for creating isolated test state and verifying expected changes.

For each test run, reset or fork the test environment so executions do not contaminate subsequent evaluations.

Absolutely no unintended production writes during evaluation.

## 11. DATABASE DESIGN

Design a relational schema including at least:

- organizations
- users
- organization_memberships
- projects
- agent_specs
- agent_versions
- integrations
- integration_connections
- data_sources
- tool_definitions
- agent_tools
- build_jobs
- build_iterations
- evaluation_suites
- evaluation_cases
- evaluation_runs
- evaluation_results
- execution_runs
- execution_events
- deployment_versions
- deployment_invocations
- approval_requests
- audit_events
- usage_records

Add appropriate foreign keys, indexes, uniqueness constraints, ownership boundaries, and timestamps.

Use versioned schemas.

Avoid storing sensitive credentials or raw private business data in execution traces.

## 12. BACKEND API

Implement typed REST endpoints covering:

- Authentication and organizations
- Project creation
- Agent creation
- Agent specification editing
- Integration management
- Tool discovery
- Build initiation
- Build pause/resume/cancel
- Build progress streaming
- Evaluation management
- Evaluation results
- Version comparison
- Deployment and rollback
- Agent invocation
- Approval requests
- Execution history
- Usage and metrics

Publish an OpenAPI specification.

Use consistent error envelopes and validation.

Add pagination for collection endpoints.

Ensure authentication and authorization are enforced on both reads and writes.

Background jobs must be idempotent or otherwise recover safely after retries.

## 13. SECURITY AND GOVERNANCE

This system will eventually perform important business operations.

Implement:
- Organization-level isolation
- Role-based permissions
- Server-side credential management
- Encrypted secrets
- Audit logs
- Tool-level authorization
- Human approval checkpoints
- Idempotency keys
- API rate limits
- Input validation
- Prompt-injection defenses at tool/data boundaries
- Resource and cost budgets
- Execution timeouts
- Safe logging defaults

Treat connected email, retrieved documents, records, and API responses as untrusted data.

Never allow retrieved content to redefine system instructions or grant tool permissions.

An agent may only invoke capabilities explicitly authorized by its deployment configuration.

Require approvals for externally visible or high-impact side effects by default.

Do not claim SOC 2, HIPAA, or other compliance certifications.

## 14. DEPLOYED AGENT RUNTIME

Separate the builder from the runtime used by deployed agents.

The builder creates and improves AgentSpecs.

The runtime executes a specific immutable, approved AgentSpec version.

Provide:
- Authenticated execution endpoint
- Input schema validation
- Tool binding
- Agent execution
- Approval interruption/resumption
- Output schema validation
- Execution tracing
- Error recovery
- Version pinning
- Rollback
- Per-agent budgets

Deployed agents must not autonomously modify their own production definitions.

Production traces may be used to propose new improvements, but those improvements must create new candidate versions and pass evaluation gates before promotion.

## 15. FRONTEND DESIGN REQUIREMENTS

Use a clean, refined design language.

Prioritize:
- Excellent information hierarchy
- Responsive layouts
- Fast interaction
- Clear navigation
- Meaningful loading and error states
- Accessible controls
- Rich execution timelines
- Expandable tool traces
- Clear version comparisons
- Understandable metrics

Create at least these pages:

/dashboard
/agents/new
/agents/[id]
/agents/[id]/build
/agents/[id]/studio
/agents/[id]/evaluations
/agents/[id]/versions
/agents/[id]/deployments
/integrations
/runs/[id]
/approvals
/settings

The build page should communicate autonomous progress particularly well.

Users must be able to see that the factory is actually testing and improving something, rather than showing a fake animation.

Use event data generated by the backend.

## 16. LONG-HORIZON EXECUTION STRATEGY

First inspect the repository and determine what already exists.

Create:

AGENTS.md:
- Repository architecture
- Engineering conventions
- Commands
- Testing expectations
- Architectural invariants
- Security constraints
- Continuation instructions

PLANS.md:
- Overall execution roadmap
- Milestones
- Dependencies
- Acceptance criteria
- Completed work
- Remaining work
- Known defects

docs/ARCHITECTURE.md:
- System components
- Data flows
- State machines
- Architecture decisions

docs/PROGRESS.md:
- Completed milestones
- Current implementation state
- Verification results
- Next actions

Then implement in this order:

PHASE 1 — Repository foundation
Working monorepo, database, migrations, backend, frontend, worker, local services, configuration.

PHASE 2 — Agent runtime
Create, persist, reconstruct, and execute a specialized agent with real Agents SDK tools.

PHASE 3 — Integrations
Connector interfaces and at least one end-to-end working integration with seeded business data.

PHASE 4 — Factory builder
Turn natural-language requirements into structured AgentSpecs and runnable agents.

PHASE 5 — Evaluation framework
Isolated test environments, assertions, traces, metrics, and evaluation results.

PHASE 6 — Autonomous improvement loop
Run → grade → diagnose → revise → retest → promote or reject.

PHASE 7 — Full frontend
Dashboard, creation workspace, build progress, agent studio, integration configuration, evaluation lab.

PHASE 8 — Deployment
Approval, deployment, invocation, logs, rollback.

PHASE 9 — Additional use cases
Quoting and hiring operations through the existing reusable architecture.

PHASE 10 — Hardening
End-to-end tests, failure recovery, tenant isolation, security review, documentation, usability fixes.

Complete each phase with working code and verification before declaring it finished.

You may overlap frontend and backend work where dependencies allow.

Do not spend the entire task writing planning documents.

## 17. VERIFICATION AND ACCEPTANCE TESTS

Implement automated tests validating the following workflows:

TEST 1 — Agent Creation
Given a business task and authorized integrations, the platform produces a valid AgentSpec and persists its version.

TEST 2 — Actual Agent Execution
A constructed agent invokes a real registered tool and returns structured output.

TEST 3 — Integration Boundaries
An agent cannot access another organization's data or an unauthorized tool.

TEST 4 — Order Processing
An order-entry agent correctly transforms a sample email into structured order lines and respects approval requirements.

TEST 5 — Autonomous Improvement
Provide an intentionally deficient initial configuration and a test suite that reveals its deficiency.

The factory must:
- Run the initial agent.
- Record a failure.
- Generate an improvement hypothesis.
- Create a new agent version.
- Execute a second evaluation.
- Compare the results.
- Promote an improved version only when evaluation evidence justifies promotion.

At least one deterministic fixture must demonstrate the complete improvement process.

Do not hardcode the passing outcome or artificially overwrite evaluation metrics.

TEST 6 — Regression Protection
A candidate that improves one scenario but breaks critical regression tests must not be promoted.

TEST 7 — Approval Enforcement
The agent must not perform an unauthorized external write.

TEST 8 — Durable Workflow
A build can recover after a worker restart without losing state or duplicating side effects.

TEST 9 — Deployment
An approved version can be deployed, invoked, monitored, and rolled back.

TEST 10 — Frontend End-to-End
A user can navigate from creating a project through inspecting a generated agent and its evaluation results.

Run the tests. Inspect failures. Fix the underlying implementation. Rerun until the required tests pass or document specific unresolved blockers.

## 18. DEVELOPER EXPERIENCE

Provide:
- README with exact setup instructions
- .env.example
- Docker Compose configuration
- Database migrations
- Seed scripts
- One-command local startup where practical
- One-command test execution
- Example API requests
- Demo credentials or a clearly documented local demo authentication mechanism
- Integration setup documentation

If OPENAI_API_KEY is absent, support a clearly labeled deterministic demo mode for the development and evaluation experience.

Do not pretend demo-mode runs were performed by a live LLM.

When an API key is present, real model-backed agent generation and execution must work.

Provide configurable model selection rather than hardcoding one expensive model.

## 19. ENGINEERING QUALITY BAR

Do not:
- Build only static mockups.
- Implement fake evaluation scores.
- Return canned agent responses disguised as live execution.
- Generate placeholder functions for core features.
- Leave major API routes disconnected.
- Add buttons that do nothing.
- Swallow exceptions silently.
- Depend on undocumented SDK interfaces.
- Expose secrets in logs.
- Run arbitrary generated code without isolation.
- Perform live business writes during tests.
- Declare success without running verification.

Prefer simple, proven infrastructure over unnecessary complexity.

Maintain strong separation of concerns.

Document important tradeoffs and assumptions.

If a dependency is unavailable, implement and test the closest meaningful local alternative and explicitly document the limitation.

## 20. AUTONOMOUS CODING INSTRUCTIONS

You have authority to make reasonable technical decisions without repeatedly asking me questions.

Do not ask for confirmation on:
- Standard architecture choices
- Library selection within the specified stack
- Database schema details
- Directory organization
- UI design details
- Implementation sequencing
- Routine engineering decisions

Ask only when blocked by missing external credentials, irreversible external operations, or genuinely consequential ambiguity.

Otherwise proceed with sensible defaults.

Work continuously through the phases within the available execution environment.

After every major milestone:
1. Run applicable tests.
2. Fix detected bugs.
3. Update PLANS.md.
4. Update docs/PROGRESS.md.
5. Commit the milestone if git operations are available and appropriate.
6. Proceed to the next incomplete milestone.

If execution is interrupted or context is compacted, use the repository's planning and progress files to resume from the last verified state.

Treat these files as durable engineering memory, not as decorative documentation.

## 21. FINAL SUCCESS CRITERIA

The project is successful when I can:

1. Start the application locally.
2. Open a professional frontend.
3. Describe a specialized business agent in natural language.
4. Attach an available data integration.
5. Start an autonomous agent build.
6. Observe the agent being configured and tested.
7. See genuine evaluation failures and diagnostic results.
8. Observe the factory generate and evaluate improved candidates.
9. Inspect differences between candidate versions.
10. Approve the best candidate.
11. Deploy the agent.
12. Execute a real supported operation against a permitted data source.
13. Inspect execution traces and results.
14. Reopen the project and see its persisted history.
15. Use the same platform to construct a different kind of business agent.

The defining feature is that the platform autonomously builds, evaluates, and improves agents rather than requiring developers to manually engineer each specialized workflow.

BEGIN NOW.

Inspect the repository, create the architecture and execution plan, and implement the application. Continue with actual code, tests, and integration until the acceptance criteria are satisfied. Do not stop after presenting a plan.