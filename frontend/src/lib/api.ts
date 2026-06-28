/**
 * Typed fetch wrappers for the AI-SDLC Jira backend API.
 *
 * Base URL is configured via the NEXT_PUBLIC_API_URL environment variable.
 * Falls back to http://localhost:8000 for local development.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

// ponytail: reads from NEXT_PUBLIC_API_TOKEN (set in .env, inlined at build time by Next.js)
function authHeaders(): Record<string, string> {
  const token = process.env.NEXT_PUBLIC_API_TOKEN
  return token ? { Authorization: `Bearer ${token}` } : {}
}

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
    headers: { "Content-Type": "application/json", ...authHeaders() },
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
  const res = await fetch(`${API_BASE}/api/projects`, { headers: authHeaders() })
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
  const res = await fetch(`${API_BASE}/api/dashboard/projects`, { headers: authHeaders() })
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
    headers: { "Content-Type": "application/json", ...authHeaders() },
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
