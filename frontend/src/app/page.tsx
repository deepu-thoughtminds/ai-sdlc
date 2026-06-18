import Link from "next/link";

export default function Home() {
  return (
    <main style={{ fontFamily: "sans-serif", maxWidth: "480px", margin: "80px auto", padding: "0 24px" }}>
      <h1>AI-SDLC Jira</h1>
      <p style={{ color: "#666", marginBottom: "32px" }}>
        AI-powered SDLC automation embedded in your Jira workflow.
      </p>
      <nav style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <Link
          href="/dashboard"
          style={{
            display: "block",
            padding: "12px 20px",
            background: "#0070f3",
            color: "#fff",
            borderRadius: "6px",
            textDecoration: "none",
            textAlign: "center",
            fontWeight: 600,
          }}
        >
          View Dashboard
        </Link>
        <Link
          href="/onboard"
          style={{
            display: "block",
            padding: "12px 20px",
            background: "#fff",
            color: "#0070f3",
            border: "1px solid #0070f3",
            borderRadius: "6px",
            textDecoration: "none",
            textAlign: "center",
            fontWeight: 600,
          }}
        >
          Onboard a Project
        </Link>
      </nav>
    </main>
  );
}
