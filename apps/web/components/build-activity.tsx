import type {Build, EventRecord, Json} from '../../../packages/contracts/src';
import {money} from '@/lib/api';

/** Plain words for what a build is doing, has done and why it stopped. The recorded events and error
    names are identifiers; a person watching a build should not have to decode them. */

const ERRORS: Record<string, string> = {
  ModelBehaviorError: "The builder's reply could not be used.",
  MaxTurnsExceeded: 'The builder used all its steps without finishing a reply.',
  TimeoutError: 'A step took longer than its time limit.',
  BudgetExceeded: 'There was not enough budget left for the next model call.',
  PermissionError: 'A step asked for something this agent is not allowed to do.',
  ValidationError: 'A reply did not have the required shape.',
  ValueError: 'The build was given something it could not use.',
  UnchangedProposal: 'It was the same as the version it was meant to improve.',
  DuplicateProposal: 'It repeated another proposal from the same round.',
  InterruptedProviderCall: 'A model call was interrupted before it answered.',
};
export function explainError(code: string) {return ERRORS[code] ?? `An unexpected error stopped this step (${code}).`;}

const STOPS: Record<string, string> = {
  target_achieved: 'The target was met on examples the builder never saw.',
  iterations_or_stagnation_limit: 'It ran out of rounds without a clear further improvement.',
  cost_or_elapsed_budget: 'It reached its cost or time limit.',
  insufficient_budget_before_provider_call: 'There was not enough budget left for the next model call.',
  held_out_score_below_target: 'Its best version scored under the target on the held-back examples.',
  critical_safety_failure: 'A version broke a safety rule.',
};
export function explainStop(reason: string) {return STOPS[reason] ?? reason.replaceAll('_', ' ');}

const text = (value: Json | undefined) => typeof value === 'string' ? value : '';
const count = (value: Json | undefined) => typeof value === 'number' ? value : 0;
const words = (value: string) => value.replaceAll('_', ' ').toLowerCase();
type Part = {passed: number; total: number};
function split(card: Json | undefined, name: string): Part | undefined {
  const splits = (card as {splits?: Record<string, Part>} | undefined)?.splits;
  return splits?.[name];
}

export type Described = {title: string; detail?: string; tone: '' | 'failed' | 'state'};

/** One line a person can read for a recorded build event. Titles start lower-case; the page capitalizes them. */
export function describeEvent(event: EventRecord): Described {
  const p = event.payload;
  switch (event.kind) {
    case 'build_created': {
      const budget = p.budget as Record<string, number> | undefined;
      return {title: 'build started', detail: budget ? `Up to ${budget.max_iterations} rounds, ${money(budget.max_cost)} and ${Math.round(budget.max_seconds / 60)} minutes. Target score ${Math.round(budget.target_score * 100)}%.` : undefined, tone: ''};
    }
    case 'build_state': return {title: `stage: ${text(p.state) === 'BUDGET_EXHAUSTED' ? 'limit reached' : words(text(p.state))}`, tone: 'state'};
    case 'integration_discovery': {
      const tools = Array.isArray(p.tools) ? p.tools.length : 0;
      return {title: 'access checked', detail: tools ? `${tools} tools available through its connections.` : 'No connections: this agent works from the request alone.', tone: ''};
    }
    case 'requirements_analyzed': return {title: 'requirements analyzed', detail: 'The first version is written.', tone: ''};
    case 'design_rejected': return {title: 'first design could not be used', detail: `${explainError(text(p.reason))} ${p.using_baseline ? 'Carrying on from the starting version.' : 'Asking again.'}`, tone: 'failed'};
    case 'factory_role_usage': return {title: `${words(text(p.role))} call`, detail: `${count(p.tokens).toLocaleString()} tokens, ${money(count(p.cost))}${count(p.reserved_cost) > 0 ? `, ${money(count(p.reserved_cost))} unresolved` : ''}.`, tone: 'state'};
    case 'evaluation_case': return {title: 'wrong answer', detail: `${text(p.name)} · ${Array.isArray(p.failures) ? p.failures.map(item => words(String(item))).join(', ') : ''}`, tone: 'failed'};
    case 'evaluation_stopped_early': return {title: 'scoring cut short', detail: 'The first twenty answers all failed in the same way, so the rest were not run.', tone: 'failed'};
    case 'candidate_compared': {
      const card = p.scorecard as {passed?: number; total?: number} | undefined, read = split(p.scorecard, 'development'), unseen = split(p.scorecard, 'selection');
      const parts = unseen && read ? `Read by the builder ${read.passed} of ${read.total} · unseen ${unseen.passed} of ${unseen.total}.` : `${card?.passed ?? 0} of ${card?.total ?? 0} correct.`;
      return {title: p.promoted ? 'version kept' : 'version not kept', detail: parts + (p.promoted ? '' : ' No clear gain over the best version.'), tone: p.promoted ? '' : 'state'};
    }
    case 'promotion_confirming': return {title: 'confirming the gain', detail: `Running ${count(p.cases)} unseen examples again, the ones whose result changed.`, tone: ''};
    case 'improvement_hypothesis': return {title: `revision proposed: version ${count(p.number)}`, detail: text(p.hypothesis), tone: ''};
    case 'proposal_rejected': return {title: 'proposal set aside', detail: explainError(text(p.reason)), tone: 'state'};
    case 'optimizer_investigation': {
      const calls = Array.isArray(p.calls) ? p.calls.length : 0, research = Array.isArray(p.research) ? p.research.length : 0;
      return {title: 'builder studied the evidence', detail: `${calls} lookups of cases, documents and earlier attempts${research ? `, ${research} web research questions` : ''}.`, tone: 'state'};
    }
    case 'candidate_screened': return {title: p.survived ? 'proposal passed screening' : 'proposal dropped in screening', detail: `Fixed ${count(p.fixed)} failing cases, broke ${count(p.broken)}.`, tone: p.survived ? '' : 'state'};
    case 'verifiers_contradicted': return {title: 'faulty checks removed', detail: `They rejected answers the examples show are correct: ${Array.isArray(p.verifiers) ? p.verifiers.join(', ') : ''}. Scoring again.`, tone: 'failed'};
    case 'provider_unavailable': return {title: 'model provider unreachable', detail: `Attempt ${count(p.attempt)}. Nothing was scored; trying again.`, tone: 'failed'};
    default: return {title: words(event.kind), detail: text(p.hypothesis) || text(p.name) || undefined, tone: ''};
  }
}

/** What the build is doing right now, or how it ended. */
export function activity(build: Build, completed: number, total: number): string {
  const c = build.checkpoint, state = build.state;
  if (typeof c.not_before === 'string' && !['PAUSED', 'WAITING_FOR_APPROVAL'].includes(state) && new Date(c.not_before).getTime() > Date.now())
    return `The model provider could not be reached${typeof c.provider_failures === 'number' ? ` (attempt ${c.provider_failures})` : ''}. Nothing was lost; trying again shortly.`;
  const progress = total ? `${completed} of ${total} answers so far` : 'starting';
  switch (state) {
    case 'DRAFT': case 'DISCOVERING': return 'Checking what the agent can reach.';
    case 'DESIGNING': return c.design_attempts ? 'The first design could not be used. Asking the builder again.' : 'The builder is writing the first version.';
    case 'BUILDING': return 'Preparing the test cases.';
    case 'TESTING': case 'RETESTING':
      if (c.validation) return `Scoring the best version on the held-back examples: ${progress}.`;
      if (c.confirm_cases) return 'Running the changed unseen examples a second time to confirm the gain.';
      return `Scoring the current version: ${progress}.`;
    case 'ANALYZING': return 'Comparing this version with the best so far.';
    case 'OPTIMIZING': return `The builder is studying the failures and writing a revision (round ${build.iteration + 1}).`;
    case 'SCREENING': return 'Trying each proposal on the failing cases before a full scoring.';
    case 'PAUSED': return text(c.waiting_reason) || 'Paused. Resume to continue from where it stopped.';
    case 'WAITING_FOR_APPROVAL': return text(c.waiting_reason) || 'Waiting for a person.';
    case 'READY_FOR_REVIEW': return 'Finished. The target was met; review and approve the version on the Deployments tab.';
    case 'BELOW_TARGET': return 'Finished. The best version is below the score required for approval.';
    case 'BUDGET_EXHAUSTED': return `Stopped. ${typeof c.stop_reason === 'string' ? explainStop(c.stop_reason) : build.error ? explainError(build.error) : ''}`;
    case 'FAILED': return `Stopped by an error. ${build.error ? explainError(build.error) : ''}`;
    case 'CANCELLED': return 'Cancelled.';
    case 'DEPLOYED': return 'Deployed.';
    default: return words(state);
  }
}

export function duration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${Math.floor(s / 3600)} h ${Math.floor(s % 3600 / 60)} min`;
}
