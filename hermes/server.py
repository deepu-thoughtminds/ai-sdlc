"""Hermes internal HTTP server — exposes /jira/* endpoints for the backend."""
import os
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from hermes.mcp_client import HermesMCPClient, JiraCredentials

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
