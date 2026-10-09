export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Collection<T> {items: T[]; total: number; offset: number; limit: number}
export interface Project {id: string; name: string; description: string}
export interface Spec {schema_version: number; name: string; purpose: string; template: string; instructions: string; model: string; tools: string[]; connection_ids: string[]; input_schema: Record<string, Json>; output_schema: Record<string, Json>; workflow: {id: string; label: string}[]; rules: Record<string, Json>; guardrails: Record<string, Json>; max_turns: number; timeout_seconds: number; max_cost: number}
export interface Version {id: string; agent_id: string; number: number; spec: Spec; hypothesis: string; approved_at: string | null; created_at: string}
export interface Agent {id: string; name: string; request: string; template: string; best_version_id: string | null; latest_version?: Version; builds?: Build[]; created_at: string}
export interface Scorecard {score: number; passed: number; total: number; critical_failures: number; metrics: Record<string, number>; splits: Record<string, {score: number; total: number; passed: number}>; mean_latency_ms: number; cost: number; tokens: number; confidence_interval_95: number[]; provisional: boolean; limitations: string; pending_reviews?: number; variability?: {repeated_cases: number; unstable_cases: number; cases: Record<string, {trials: number; pass_rate: number; standard_deviation: number; min: number; max: number}>}}
export interface Iteration {id: string; number: number; version_id: string; scorecard: Scorecard; diagnosis: Json; promoted: boolean}
export interface Build {id: string; state: string; iteration: number; spent: number; budget: Budget; checkpoint: Record<string, Json>; error: string | null; iterations?: Iteration[]}
export interface Budget {max_iterations: number; max_cost: number; max_seconds: number; target_score: number; stagnation_limit: number}
export interface Evaluation {id: string; version_id: string; suite_id: string; status: string; scorecard: Scorecard; results?: EvaluationResult[]; created_at: string}
export interface Check {category: string; path?: string; passed: boolean; expected?: Json; actual?: Json; evidence?: string; pending?: boolean; reviewed_by?: string; reviewed_at?: string; rubric?: Json; grades?: Json}
export interface EvaluationResult {id: string; case_id: string; execution_id: string; passed: boolean; checks: Check[]; failures: string[]; trial: number}
export interface EvalCase {id: string; name: string; split: string; source: string; input: Record<string, Json>; assertions: Json[]; critical: boolean}
export interface Connection {id: string; name: string; kind: string; status: string; config: Record<string, Json>; permissions: Record<string, boolean>; has_secret: boolean; tools?: Tool[]; data_sources?: DataSource[]}
export interface Tool {id: string; name: string; write: boolean; definition: Record<string, Json>}
export interface DataSource {id: string; name: string; schema: Json; model_visible: boolean; records: Json[]}
export interface Deployment {spent: number; reserved: number; id: string; agent_id: string; version_id: string; active: boolean; created_at: string; policy: Record<string, Json>}
export interface Run {id: string; version_id: string; mode: string; status: string; input: Json; output: Json; metrics: Record<string, Json>; error: string | null; created_at: string; events?: EventRecord[]}
export interface EventRecord {id: string; kind: string; payload: Record<string, Json>; created_at: string}
export interface Approval {id: string; run_id: string; action: Json; status: string; created_at: string}
export interface Me {user: {email: string}; organization: {name: string}; role: string; execution_mode: string; model: string}
export interface Metrics {agents: number; deployed: number; pending_approvals: number; runs: number; failure_rate: number; cost: number; mean_latency_ms: number; execution_mode: string; evaluations: Evaluation[]}
