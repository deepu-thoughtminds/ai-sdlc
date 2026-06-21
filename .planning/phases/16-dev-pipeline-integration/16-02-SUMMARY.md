---
phase: 16-dev-pipeline-integration
plan: "02"
subsystem: dev-pipeline-orchestrator / webhook-routing
tags: [orchestrator, webhook, idempotency, codegen, pr, tdd, devpipe]
dependency_graph:
  requires:
    - backend.services.hermes_client.get_comments
    - backend.services.hermes_client.get_confluence_page_content
    - backend.services.confluence_url_finder.find_latest_architecture_url
  provides:
    - backend.services.dev_pipeline.run
    - POST /webhook/jira-comment "@jarvis start coding" → dev_pipeline.run (background)
  affects:
    - backend/routers/webhook.py
tech_stack:
  added: []
  patterns:
    - PipelineState idempotency guard (status="running" committed before asyncio.create_task)
    - CR-02 background-task DB session isolation (fresh SessionLocal() inside coroutine, never the request-scoped db)
    - WR-01 post Jira comment before finalizing status="complete"
    - WR-03 best-effort failure notification wrapped in its own try/except
    - shutil.rmtree(workspace_path, ignore_errors=True) guaranteed via try/finally around clone→codegen→PR
key_files:
  created:
    - backend/services/dev_pipeline.py
    - backend/tests/test_dev_pipeline.py
  modified:
    - backend/routers/webhook.py
    - backend/tests/test_webhook.py
decisions:
  - "dev_pipeline.run() re-uses an existing PipelineState(stage=dev_pipeline, status=running) row if present, else creates one — mirrors architecture_pipeline.py so webhook.py and direct test calls share the same contract"
  - "No Confluence URL found or generate_code_changes returns [] are both graceful degradation paths: status=complete, informative Jira comment posted, no PR opened"
  - "clone_repository / generate_code_changes / apply_commit_push_and_open_pr / get_codebase_summary are all synchronous — called without await, unlike the async hermes_client and post_comment functions"
  - "Token values (jira_token/confluence_token/github_token) are decrypted locally and passed only to hermes_client/pr_creator calls — never to generate_code_changes (T-16-05) and never logged (T-16-06)"
  - "webhook.py start_coding branch is a byte-for-byte structural copy of the architecture branch's idempotency-guard pattern, substituting stage=dev_pipeline and dev_pipeline.run"
metrics:
  completed_date: "2026-06-21"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 2
  tests_added: 10
  tests_passing: "29 (6 dev_pipeline + 23 webhook, includes 4 new start_coding tests)"
notes:
  - "Wave 2 gsd-executor subagent failed (Bash access denied in its worktree); both tasks were executed inline in the main session by the orchestrating agent instead of via subagent — deviation from standard wave execution, necessitated by tool-permission denial rather than plan content."
  - "Pre-existing failures in backend/tests/test_assign_pipeline.py (4 tests, MentionResult 'stage' kwarg mismatch) are unrelated to this phase — confirmed via git stash that they fail identically on the pre-Phase-16 commit."
