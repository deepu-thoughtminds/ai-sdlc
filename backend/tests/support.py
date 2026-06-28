"""Shared helpers for MongoDB-backed tests."""

from repositories import projects_repo


def make_project(db, *, project_key="P", name="P", **overrides):
    """Insert a minimal project document and return it (a Doc with .id).

    Credential fields default to the literal "c" — tests that don't exercise
    encryption don't care about the value. Pass overrides to customize.
    """
    fields = dict(
        name=name,
        project_key=project_key,
        jira_url="https://x.atlassian.net",
        jira_email="",
        confluence_url="https://x.atlassian.net/wiki",
        github_url=None,
        jira_token="c",
        github_token="c",
        confluence_token="c",
        github_repo="c",
    )
    fields.update(overrides)
    return projects_repo.create(db, **fields)
