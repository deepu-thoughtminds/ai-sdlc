"use client"

import { useState } from "react"
import Link from "next/link"
import { createProject } from "../../lib/api"
import type { ProjectCreatePayload, ProjectPublic } from "../../lib/api"

type Status = "idle" | "submitting" | "success" | "error"

interface FormState {
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

const emptyForm: FormState = {
  name: "",
  project_key: "",
  jira_url: "",
  jira_email: "",
  jira_token: "",
  github_token: "",
  github_repo: "",
  confluence_url: "",
  confluence_token: "",
}

export default function OnboardPage() {
  const [form, setForm] = useState<FormState>(emptyForm)
  const [status, setStatus] = useState<Status>("idle")
  const [errorMessage, setErrorMessage] = useState<string>("")
  const [createdProject, setCreatedProject] = useState<ProjectPublic | null>(null)

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setStatus("submitting")
    setErrorMessage("")

    try {
      const payload: ProjectCreatePayload = {
        name: form.name,
        project_key: form.project_key,
        jira_url: form.jira_url,
        jira_email: form.jira_email,
        jira_token: form.jira_token,
        github_token: form.github_token,
        github_repo: form.github_repo,
        confluence_url: form.confluence_url,
        confluence_token: form.confluence_token,
      }
      const project = await createProject(payload)
      setCreatedProject(project)
      setStatus("success")
    } catch (e) {
      setStatus("error")
      setErrorMessage(e instanceof Error ? e.message : "Unknown error")
    }
  }

  const fieldStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    marginBottom: "16px",
  }

  const labelStyle: React.CSSProperties = {
    fontWeight: "600",
    fontSize: "14px",
  }

  const inputStyle: React.CSSProperties = {
    padding: "8px 12px",
    fontSize: "14px",
    border: "1px solid #ccc",
    borderRadius: "4px",
    width: "100%",
    boxSizing: "border-box",
  }

  return (
    <main style={{ maxWidth: "560px", margin: "40px auto", padding: "0 16px" }}>
      <h1>Onboard New Project</h1>

      {status === "success" && createdProject && (
        <div
          role="status"
          style={{
            backgroundColor: "#d4edda",
            border: "1px solid #c3e6cb",
            borderRadius: "4px",
            padding: "12px 16px",
            marginBottom: "24px",
            color: "#155724",
          }}
        >
          <strong>Project onboarded! ID: {createdProject.id}</strong>
          <br />
          <Link href="/">Go to Dashboard</Link>
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          style={{
            backgroundColor: "#f8d7da",
            border: "1px solid #f5c6cb",
            borderRadius: "4px",
            padding: "12px 16px",
            marginBottom: "24px",
            color: "#721c24",
          }}
        >
          {errorMessage}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div style={fieldStyle}>
          <label htmlFor="name" style={labelStyle}>
            Project Name
          </label>
          <input
            id="name"
            name="name"
            type="text"
            required
            placeholder="My Project"
            value={form.name}
            onChange={handleChange}
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="project_key" style={labelStyle}>
            Project Key
          </label>
          <input
            id="project_key"
            name="project_key"
            type="text"
            required
            placeholder="MYPROJ"
            value={form.project_key}
            onChange={handleChange}
            style={inputStyle}
          />
          <small style={{ color: "#666", fontSize: "12px" }}>
            Uppercase alphanumeric, e.g. MYPROJ or MY-PROJ
          </small>
        </div>

        <div style={fieldStyle}>
          <label htmlFor="jira_url" style={labelStyle}>
            Jira URL
          </label>
          <input
            id="jira_url"
            name="jira_url"
            type="text"
            required
            placeholder="https://yourorg.atlassian.net"
            value={form.jira_url}
            onChange={handleChange}
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="jira_email" style={labelStyle}>
            Jira Account Email
          </label>
          <input
            id="jira_email"
            name="jira_email"
            type="email"
            required
            placeholder="you@example.com"
            value={form.jira_email}
            onChange={handleChange}
            style={inputStyle}
          />
          <small style={{ color: "#666", fontSize: "12px" }}>
            Atlassian account email used with the API token above
          </small>
        </div>

        <div style={fieldStyle}>
          <label htmlFor="jira_token" style={labelStyle}>
            Jira API Token
          </label>
          <input
            id="jira_token"
            name="jira_token"
            type="password"
            required
            placeholder="Jira API token"
            value={form.jira_token}
            onChange={handleChange}
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="github_token" style={labelStyle}>
            GitHub Token
          </label>
          <input
            id="github_token"
            name="github_token"
            type="password"
            required
            placeholder="GitHub personal access token"
            value={form.github_token}
            onChange={handleChange}
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="github_repo" style={labelStyle}>
            GitHub Repository
          </label>
          <input
            id="github_repo"
            name="github_repo"
            type="text"
            required
            placeholder="acme/my-app"
            value={form.github_repo}
            onChange={handleChange}
            style={inputStyle}
          />
          <small style={{ color: "#666", fontSize: "12px" }}>
            Owner/repo slug, e.g. acme/my-app
          </small>
        </div>

        <div style={fieldStyle}>
          <label htmlFor="confluence_url" style={labelStyle}>
            Confluence URL
          </label>
          <input
            id="confluence_url"
            name="confluence_url"
            type="text"
            required
            placeholder="https://yourorg.atlassian.net/wiki"
            value={form.confluence_url}
            onChange={handleChange}
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <label htmlFor="confluence_token" style={labelStyle}>
            Confluence Token
          </label>
          <input
            id="confluence_token"
            name="confluence_token"
            type="password"
            required
            placeholder="Confluence API token"
            value={form.confluence_token}
            onChange={handleChange}
            style={inputStyle}
          />
        </div>

        <button
          type="submit"
          disabled={status === "submitting"}
          style={{
            padding: "10px 24px",
            backgroundColor: status === "submitting" ? "#6c757d" : "#0070f3",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            fontSize: "14px",
            fontWeight: "600",
            cursor: status === "submitting" ? "not-allowed" : "pointer",
          }}
        >
          {status === "submitting" ? "Submitting..." : "Onboard Project"}
        </button>
      </form>
    </main>
  )
}
