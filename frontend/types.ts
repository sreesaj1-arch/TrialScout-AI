export type Role =
  | 'user'
  | 'assistant';


/*
 * ============================================================
 * TrialScout specialist agents
 * ============================================================
 */

export type TrialScoutAgentKey =
  | 'orchestrator'
  | 'discovery'
  | 'analysis'
  | 'fhir_screening'
  | 'matching_ranking'
  | 'research_knowledge'
  | 'url_context'
  | 'unknown';


export interface AgentDisplayInfo {
  key: TrialScoutAgentKey;

  /*
   * Friendly frontend label.
   *
   * We intentionally do not expose ugly internal function
   * names such as "trial_discovery_agent" to end users.
   */
  label: string;

  /*
   * Human-readable activity displayed while the agent
   * is processing the request.
   */
  activity: string;

  /*
   * Actual ADK / Agent Runtime name.
   *
   * Useful for debugging but not normally displayed.
   */
  runtimeName?: string;
}


/*
 * Update emitted while the Agent Runtime stream is active.
 */

export interface AgentRoutingUpdate {
  activeAgent: AgentDisplayInfo;

  /*
   * Agents observed during this request.
   *
   * Example:
   *
   * Orchestrator
   *      ↓
   * Discovery Agent
   */
  route: AgentDisplayInfo[];
}


/*
 * ============================================================
 * Trial cards
 * ============================================================
 */

export interface TrialData {
  id: string;
  title: string;
  nctId: string;
  status: string;
  phase: string;
  condition: string;
  sponsor: string;
  location: string;
  distance?: string;
  summary: string;
  url: string;
}


/*
 * ============================================================
 * Chat message
 * ============================================================
 */

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;

  trials?: TrialData[];

  /*
   * Used for the temporary "working" bubble.
   */
  isTyping?: boolean;

  /*
   * Specialist currently handling the request, or the
   * specialist that handled the final response.
   */
  agent?: AgentDisplayInfo;

  /*
   * Real routing path observed from Agent Runtime events.
   */
  agentRoute?: AgentDisplayInfo[];
}