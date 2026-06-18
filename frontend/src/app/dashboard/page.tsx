"use client"

import { useEffect, useState } from "react"
import { getDashboard, ProjectWithTickets, TicketStatusPublic } from "../../lib/api"

const STAGE_COLORS: Record<string, string> = {
  description: "#cfe2ff",
  architecture: "#fff3cd",
  dev: "#d1e7dd",
  qa: "#f8d7da",
  done: "#e2e3e5",
}

function getLastUpdated(project: ProjectWithTickets): string {
  if (project.ticket_statuses.length === 0) {
    return new Date(project.created_at).toLocaleDateString()
  }
  const latest = project.ticket_statuses.reduce((prev, curr) =>
    new Date(curr.updated_at) > new Date(prev.updated_at) ? curr : prev
  )
  return new Date(latest.updated_at).toLocaleDateString()
}

export default function DashboardPage() {
  const [projects, setProjects] = useState<ProjectWithTickets[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    getDashboard()
      .then(setProjects)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <main style={{ fontFamily: "sans-serif", maxWidth: "960px", margin: "0 auto", padding: "24px" }}>
      <nav style={{ display: "flex", gap: "16px", marginBottom: "24px" }}>
        <a href="/" style={{ textDecoration: "none", color: "#666" }}>&#8592; Home</a>
        <a href="/onboard" style={{ textDecoration: "none", color: "#0070f3" }}>+ Onboard Project</a>
      </nav>

      <h1 style={{ marginBottom: "24px" }}>Project Dashboard</h1>

      {loading && <p>Loading...</p>}

      {error && (
        <div style={{ background: "#f8d7da", color: "#842029", padding: "12px 16px", borderRadius: "4px", marginBottom: "16px" }}>
          Error: {error}
        </div>
      )}

      {!loading && !error && projects.length === 0 && (
        <div style={{ padding: "24px", background: "#f8f9fa", borderRadius: "8px", textAlign: "center" }}>
          <p>No projects onboarded yet.</p>
          <a href="/onboard" style={{ color: "#0070f3" }}>Add one at /onboard</a>
        </div>
      )}

      {!loading && projects.length > 0 && (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "32px" }}>
            <thead>
              <tr style={{ background: "#f1f3f5" }}>
                <th style={{ padding: "10px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Project Name</th>
                <th style={{ padding: "10px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Project Key</th>
                <th style={{ padding: "10px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Jira URL</th>
                <th style={{ padding: "10px 12px", textAlign: "right", border: "1px solid #dee2e6" }}>Active Tickets</th>
                <th style={{ padding: "10px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => {
                const activeCount = project.ticket_statuses.filter(
                  (ts) => ts.pipeline_stage !== "done"
                ).length
                return (
                  <tr key={project.id} style={{ borderBottom: "1px solid #dee2e6" }}>
                    <td style={{ padding: "10px 12px", border: "1px solid #dee2e6" }}>{project.name}</td>
                    <td style={{ padding: "10px 12px", border: "1px solid #dee2e6", fontFamily: "monospace" }}>{project.project_key}</td>
                    <td style={{ padding: "10px 12px", border: "1px solid #dee2e6" }}>
                      <a href={project.jira_url} target="_blank" rel="noreferrer" style={{ color: "#0070f3" }}>
                        {project.jira_url}
                      </a>
                    </td>
                    <td style={{ padding: "10px 12px", border: "1px solid #dee2e6", textAlign: "right" }}>{activeCount}</td>
                    <td style={{ padding: "10px 12px", border: "1px solid #dee2e6" }}>{getLastUpdated(project)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {projects
            .filter((p) => p.ticket_statuses.length > 0)
            .map((project) => {
              const activeTickets = project.ticket_statuses.filter(
                (ts) => ts.pipeline_stage !== "done"
              )
              if (activeTickets.length === 0) return null
              return (
                <div key={project.id} style={{ marginBottom: "32px" }}>
                  <h3 style={{ marginBottom: "12px" }}>{project.name} &mdash; Active Tickets</h3>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ background: "#f1f3f5" }}>
                        <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Ticket Key</th>
                        <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Pipeline Stage</th>
                        <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Last Updated</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeTickets.map((ts: TicketStatusPublic) => (
                        <tr key={ts.id} style={{ borderBottom: "1px solid #dee2e6" }}>
                          <td style={{ padding: "8px 12px", border: "1px solid #dee2e6", fontFamily: "monospace" }}>{ts.ticket_key}</td>
                          <td style={{ padding: "8px 12px", border: "1px solid #dee2e6" }}>
                            <span
                              style={{
                                backgroundColor: STAGE_COLORS[ts.pipeline_stage] ?? "#fff",
                                padding: "2px 6px",
                                borderRadius: "4px",
                              }}
                            >
                              {ts.pipeline_stage}
                            </span>
                          </td>
                          <td style={{ padding: "8px 12px", border: "1px solid #dee2e6" }}>
                            {new Date(ts.updated_at).toLocaleDateString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })}
        </>
      )}
    </main>
  )
}
