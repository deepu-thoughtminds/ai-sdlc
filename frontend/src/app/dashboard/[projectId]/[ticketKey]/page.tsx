"use client"

import { useEffect, useState, type ReactNode } from "react"
import { useParams } from "next/navigation"
import {
  getAgentEvents,
  getTicketDetail,
  AgentEventPublic,
  TicketDetail,
} from "../../../../lib/api"

const STATUS_COLORS: Record<string, string> = {
  success: "#d1e7dd",
  failed: "#f8d7da",
  in_progress: "#fff3cd",
}

function isUrl(value: string | null): boolean {
  return !!value && /^https?:\/\//.test(value)
}

function Section({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section style={{ marginBottom: "32px" }}>
      <h2 style={{ fontSize: "18px", marginBottom: "12px" }}>{title}</h2>
      {children}
    </section>
  )
}

function EventDetail({ detail }: { detail: string | null }) {
  if (!detail) return null
  if (isUrl(detail)) {
    return (
      <a href={detail} target="_blank" rel="noreferrer" style={{ color: "#0070f3" }}>
        {detail}
      </a>
    )
  }
  return <span style={{ color: "#555" }}>{detail}</span>
}

export default function TicketDetailPage() {
  const params = useParams<{ projectId: string; ticketKey: string }>()
  const projectId = Number(params.projectId)
  const ticketKey = decodeURIComponent(params.ticketKey)

  const [detail, setDetail] = useState<TicketDetail | null>(null)
  const [events, setEvents] = useState<AgentEventPublic[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!projectId || !ticketKey) return
    Promise.all([
      getTicketDetail(projectId, ticketKey),
      getAgentEvents(projectId, ticketKey),
    ])
      .then(([d, e]) => {
        setDetail(d)
        setEvents(e)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [projectId, ticketKey])

  // Thinking & Actions share one chronological feed; decisions and goals are
  // pulled out into their own focused sections.
  const thinkingAndActions = events.filter(
    (e) => e.event_type === "thinking" || e.event_type === "action"
  )
  const decisions = events.filter((e) => e.event_type === "decision")
  const goals = events.filter((e) => e.event_type === "goal")

  return (
    <main style={{ fontFamily: "sans-serif", maxWidth: "900px", margin: "0 auto", padding: "24px" }}>
      <nav style={{ display: "flex", gap: "16px", marginBottom: "24px" }}>
        <a href="/dashboard" style={{ textDecoration: "none", color: "#666" }}>&#8592; Dashboard</a>
      </nav>

      <h1 style={{ marginBottom: "4px", fontFamily: "monospace" }}>{ticketKey}</h1>
      {detail && (
        <p style={{ color: "#666", marginTop: 0 }}>
          {detail.summary ?? "—"} &nbsp;·&nbsp; stage: <strong>{detail.pipeline_stage}</strong>
          {detail.current_status ? <> &nbsp;·&nbsp; {detail.current_status}</> : null}
        </p>
      )}

      {loading && <p>Loading...</p>}

      {error && (
        <div style={{ background: "#f8d7da", color: "#842029", padding: "12px 16px", borderRadius: "4px", marginBottom: "16px" }}>
          Error: {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* 1. Thinking & Actions */}
          <Section title="🧠 Thinking &amp; Actions">
            {thinkingAndActions.length === 0 ? (
              <p style={{ color: "#888" }}>No agent activity recorded yet.</p>
            ) : (
              <ol style={{ listStyle: "none", padding: 0, margin: 0, borderLeft: "2px solid #e9ecef" }}>
                {thinkingAndActions.map((e) => (
                  <li key={e.id} style={{ padding: "8px 0 8px 16px", position: "relative" }}>
                    <span
                      style={{
                        display: "inline-block",
                        fontSize: "11px",
                        fontWeight: 600,
                        textTransform: "uppercase",
                        color: e.event_type === "action" ? "#0a58ca" : "#6c757d",
                        marginRight: "8px",
                      }}
                    >
                      {e.event_type === "action" ? `🔧 ${e.tool_name ?? "tool"}` : "💭 thinking"}
                    </span>
                    {e.event_type === "thinking" ? (
                      <span style={{ whiteSpace: "pre-wrap" }}>{e.content}</span>
                    ) : (
                      <EventDetail detail={e.detail} />
                    )}
                  </li>
                ))}
              </ol>
            )}
          </Section>

          {/* 2. Decisions */}
          <Section title="⚖️ Decisions">
            {decisions.length === 0 ? (
              <p style={{ color: "#888" }}>No decisions recorded yet.</p>
            ) : (
              <ul style={{ paddingLeft: "20px", margin: 0 }}>
                {decisions.map((e) => (
                  <li key={e.id} style={{ marginBottom: "8px" }}>
                    <strong>{e.content}</strong>
                    {e.detail ? <> — <span style={{ color: "#555" }}>{e.detail}</span></> : null}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* 3. Goal achieved */}
          <Section title="🎯 Goal Achieved">
            {goals.length === 0 ? (
              <p style={{ color: "#888" }}>Not completed yet.</p>
            ) : (
              <ul style={{ paddingLeft: "20px", margin: 0 }}>
                {goals.map((e) => (
                  <li key={e.id} style={{ marginBottom: "8px" }}>
                    <strong>{e.content}</strong>
                    {e.detail ? <> — <EventDetail detail={e.detail} /></> : null}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* Stage timeline (coarse milestones) */}
          <Section title="📋 Stage Timeline">
            {!detail || detail.transactions.length === 0 ? (
              <p style={{ color: "#888" }}>No stage transitions recorded yet.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: "#f1f3f5" }}>
                    <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Stage</th>
                    <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Event</th>
                    <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>Status</th>
                    <th style={{ padding: "8px 12px", textAlign: "left", border: "1px solid #dee2e6" }}>When</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.transactions.map((t) => (
                    <tr key={t.id} style={{ borderBottom: "1px solid #dee2e6" }}>
                      <td style={{ padding: "8px 12px", border: "1px solid #dee2e6" }}>{t.stage}</td>
                      <td style={{ padding: "8px 12px", border: "1px solid #dee2e6" }}>
                        {t.result_url ? (
                          <a href={t.result_url} target="_blank" rel="noreferrer" style={{ color: "#0070f3" }}>
                            {t.event}
                          </a>
                        ) : (
                          t.event
                        )}
                      </td>
                      <td style={{ padding: "8px 12px", border: "1px solid #dee2e6" }}>
                        <span
                          style={{
                            backgroundColor: STATUS_COLORS[t.status] ?? "#fff",
                            padding: "2px 6px",
                            borderRadius: "4px",
                          }}
                        >
                          {t.status}
                        </span>
                      </td>
                      <td style={{ padding: "8px 12px", border: "1px solid #dee2e6" }}>
                        {new Date(t.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </>
      )}
    </main>
  )
}
