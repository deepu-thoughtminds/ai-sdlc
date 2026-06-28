/**
 * Typed fetch wrappers for the AI-SDLC Jira backend API.
 *
 * Base URL is configured via the NEXT_PUBLIC_API_URL environment variable.
 * Falls back to http://localhost:8000 for local development.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProjectCreatePayload {
  name: string
  project_key: string
  jira_url: string
  jira_email: string
  jira_token: string
  github_token: string
  github_repo: string
  confluence_url: string
  confluence_token: string
}

export interface ProjectPublic {
  id: number
  name: string
  project_key: string
  jira_url: string
  confluence_url: string
  github_repo: string
  created_at: string
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Create a new project. Sends plaintext tokens to the backend; the backend
 * encrypts them before storing. Returns the created project without tokens.
 */
export async function createProject(
  data: ProjectCreatePayload
): Promise<ProjectPublic> {
  const res = await fetch(`${API_BASE}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(
      (err as { detail?: string }).detail ?? `HTTP ${res.status}`
    )
  }
  return res.json() as Promise<ProjectPublic>
}

/**
 * List all projects. Returns compact project items without token fields.
 */
export async function listProjects(): Promise<ProjectPublic[]> {
  const res = await fetch(`${API_BASE}/api/projects`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<ProjectPublic[]>
}

// ---------------------------------------------------------------------------
// Dashboard types
// ---------------------------------------------------------------------------

export interface TicketStatusPublic {
  id: number
  ticket_key: string
  pipeline_stage: string
  updated_at: string
}

export interface TicketStatusCreate {
  ticket_key: string
  pipeline_stage: string
}

export interface ProjectWithTickets {
  id: number
  name: string
  project_key: string
  jira_url: string
  confluence_url: string
  github_repo: string
  created_at: string
  ticket_statuses: TicketStatusPublic[]
}

// ---------------------------------------------------------------------------
// Dashboard API functions
// ---------------------------------------------------------------------------

/**
 * Fetch all projects with their nested ticket pipeline statuses.
 */
export async function getDashboard(): Promise<ProjectWithTickets[]> {
  const res = await fetch(`${API_BASE}/api/dashboard/projects`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<ProjectWithTickets[]>
}

/**
 * Upsert a ticket's pipeline stage for a given project.
 * Creates a new row if (projectId, ticket_key) does not exist; updates if it does.
 */
export async function upsertTicketStatus(
  projectId: number,
  data: TicketStatusCreate
): Promise<TicketStatusPublic> {
  const res = await fetch(`${API_BASE}/api/dashboard/projects/${projectId}/tickets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(
      (err as { detail?: string }).detail ?? `HTTP ${res.status}`
    )
  }
  return res.json() as Promise<TicketStatusPublic>
}

// ---------------------------------------------------------------------------
// Ticket detail & agent activity types
// ---------------------------------------------------------------------------

export interface StageTransactionPublic {
  id: number
  ticket_key: string
  stage: string
  event: string
  status: string
  result_url: string | null
  detail: string | null
  created_at: string
}

export interface TicketDetail {
  id: number
  ticket_key: string
  pipeline_stage: string
  current_status: string | null
  summary: string | null
  issue_type: string | null
  created_at: string
  updated_at: string
  transactions: StageTransactionPublic[]
}

/** One captured agent event: thinking | action | decision | goal. */
export interface AgentEventPublic {
  id: number
  ticket_key: string
  stage: string
  event_type: "thinking" | "action" | "decision" | "goal"
  content: string
  tool_name: string | null
  detail: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// Ticket detail & agent activity API functions
// ---------------------------------------------------------------------------

/**
 * Fetch a single ticket's feature details + full stage-transaction timeline.
 */
export async function getTicketDetail(
  projectId: number,
  ticketKey: string
): Promise<TicketDetail> {
  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/tickets/${encodeURIComponent(ticketKey)}`
  )
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<TicketDetail>
}

/**
 * Fetch the captured agent activity log (thinking/action/decision/goal) for a
 * ticket, oldest-first.
 */
export async function getAgentEvents(
  projectId: number,
  ticketKey: string
): Promise<AgentEventPublic[]> {
  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/tickets/${encodeURIComponent(ticketKey)}/agent-events`
  )
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<AgentEventPublic[]>
}
