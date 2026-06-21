"""Hermes internal HTTP server — exposes /jira/* endpoints for the backend."""
import os
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from hermes.mcp_client import HermesMCPClient, JiraCredentials, ConfluenceCredentials

# Module-level singleton — tests override via app.dependency_overrides
_mcp_client = HermesMCPClient()


def get_mcp_client() -> HermesMCPClient:
    return _mcp_client


app = FastAPI(title="Hermes", version="1.0")


class AddCommentRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_token: str
    issue_key: str
    body: str


class UpdateDescriptionRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_token: str
    issue_key: str
    description: str


class SprintBacklogRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_token: str
    project_key: str


class AssignIssueRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_token: str
    issue_key: str
    display_name: str


@app.post("/jira/comment")
async def post_comment(req: AddCommentRequest, client: HermesMCPClient = Depends(get_mcp_client)):
    creds = JiraCredentials(jira_url=req.jira_url, jira_email=req.jira_email, jira_token=req.jira_token)
    try:
        comment_id = await client.add_comment(req.issue_key, req.body, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"comment_id": comment_id}


@app.put("/jira/description")
async def put_description(req: UpdateDescriptionRequest, client: HermesMCPClient = Depends(get_mcp_client)):
    creds = JiraCredentials(jira_url=req.jira_url, jira_email=req.jira_email, jira_token=req.jira_token)
    try:
        await client.update_description(req.issue_key, req.description, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {}


@app.post("/jira/sprint-backlog")
async def post_sprint_backlog(req: SprintBacklogRequest, client: HermesMCPClient = Depends(get_mcp_client)):
    creds = JiraCredentials(jira_url=req.jira_url, jira_email=req.jira_email, jira_token=req.jira_token)
    try:
        issues = await client.get_sprint_issues(req.project_key, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return issues


@app.post("/jira/assign")
async def post_assign(req: AssignIssueRequest, client: HermesMCPClient = Depends(get_mcp_client)):
    creds = JiraCredentials(jira_url=req.jira_url, jira_email=req.jira_email, jira_token=req.jira_token)
    try:
        account_id = await client.lookup_user(req.display_name, creds)
        await client.assign_issue(req.issue_key, account_id, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"account_id": account_id}


# ---------------------------------------------------------------------------
# Phase 17 Plan 01: Jira status transition endpoint (PRMERGE-02)
# ---------------------------------------------------------------------------


class TransitionIssueRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_token: str
    issue_key: str
    status_name: str


@app.post("/jira/status")
async def post_transition_issue(
    req: TransitionIssueRequest, client: HermesMCPClient = Depends(get_mcp_client)
):
    """Transition a Jira issue to a new status via HermesMCPClient.transition_issue.

    Returns {"success": true/false}. The transition_issue method never raises —
    failures are returned as {"success": false} rather than HTTP 500.
    """
    creds = JiraCredentials(
        jira_url=req.jira_url,
        jira_email=req.jira_email,
        jira_token=req.jira_token,
    )
    result = await client.transition_issue(req.issue_key, req.status_name, creds)
    return {"success": result}


# ---------------------------------------------------------------------------
# Confluence endpoints
# ---------------------------------------------------------------------------


class CreateConfluencePageRequest(BaseModel):
    confluence_url: str
    confluence_email: str
    confluence_token: str
    space_key: str
    title: str
    body_html: str


class UpdateConfluencePageRequest(BaseModel):
    confluence_url: str
    confluence_email: str
    confluence_token: str
    title: str
    body_html: str
    version: int


@app.post("/confluence/page")
async def post_confluence_page(req: CreateConfluencePageRequest, client: HermesMCPClient = Depends(get_mcp_client)):
    creds = ConfluenceCredentials(
        confluence_url=req.confluence_url,
        confluence_email=req.confluence_email,
        confluence_token=req.confluence_token,
    )
    try:
        result = await client.create_confluence_page(req.space_key, req.title, req.body_html, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@app.put("/confluence/page/{page_id}")
async def put_confluence_page(page_id: str, req: UpdateConfluencePageRequest, client: HermesMCPClient = Depends(get_mcp_client)):
    creds = ConfluenceCredentials(
        confluence_url=req.confluence_url,
        confluence_email=req.confluence_email,
        confluence_token=req.confluence_token,
    )
    try:
        result = await client.update_confluence_page(page_id, req.title, req.body_html, req.version, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@app.get("/confluence/search")
async def get_confluence_search(
    space_key: str,
    title: str,
    confluence_url: str,
    confluence_email: str,
    confluence_token: str,
    client: HermesMCPClient = Depends(get_mcp_client),
):
    creds = ConfluenceCredentials(
        confluence_url=confluence_url,
        confluence_email=confluence_email,
        confluence_token=confluence_token,
    )
    try:
        result = await client.find_confluence_page(space_key, title, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    # Return {} (empty dict) when not found — the hermes "not found" sentinel
    return result if result is not None else {}


# ---------------------------------------------------------------------------
# Phase 16 Plan 01: Jira comments and Confluence page fetch endpoints
# ---------------------------------------------------------------------------


class GetCommentsRequest(BaseModel):
    jira_url: str
    jira_email: str
    jira_token: str
    issue_key: str


@app.post("/jira/comments")
async def post_get_comments(
    req: GetCommentsRequest,
    client: HermesMCPClient = Depends(get_mcp_client),
):
    """Fetch comment history for a Jira issue via MCP.

    Returns a flat list of comment dicts.
    Uses POST (not GET) because credentials are passed in the request body
    to avoid token exposure in URL query parameters.
    """
    creds = JiraCredentials(
        jira_url=req.jira_url,
        jira_email=req.jira_email,
        jira_token=req.jira_token,
    )
    try:
        comments = await client.get_comments(req.issue_key, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return comments


@app.get("/confluence/page/{page_id}")
async def get_confluence_page(
    page_id: str,
    confluence_url: str,
    confluence_email: str,
    confluence_token: str,
    client: HermesMCPClient = Depends(get_mcp_client),
):
    """Fetch the body content of a Confluence page by page ID via MCP.

    Returns {"body": "<page content string>"}.
    Uses GET with query param credentials, mirroring GET /confluence/search convention.
    """
    creds = ConfluenceCredentials(
        confluence_url=confluence_url,
        confluence_email=confluence_email,
        confluence_token=confluence_token,
    )
    try:
        body = await client.get_confluence_page(page_id, creds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"body": body}
