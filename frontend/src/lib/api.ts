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
  jira_token: string
  github_token: string
  confluence_url: string
  confluence_token: string
}

export interface ProjectPublic {
  id: number
  name: string
  project_key: string
  jira_url: string
  confluence_url: string
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
