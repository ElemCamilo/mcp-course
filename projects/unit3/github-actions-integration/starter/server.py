#!/usr/bin/env python3
"""
Module 2: GitHub Actions Integration - STARTER CODE
Extend your PR Agent with webhook handling and MCP Prompts for CI/CD workflows.
"""

import json
import os
import asyncio
import shutil
import subprocess
from typing import Optional
from pathlib import Path
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# Initialize the FastMCP server
mcp = FastMCP("pr-agent-actions")

# PR template directory (shared between starter and solution)
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

# Default PR templates
DEFAULT_TEMPLATES = {
    "bug.md": "Bug Fix",
    "feature.md": "Feature",
    "docs.md": "Documentation",
    "refactor.md": "Refactor",
    "test.md": "Test",
    "performance.md": "Performance",
    "security.md": "Security"
}

EVENTS_FILE = Path(__file__).parent / "github_events.json"

# Type mapping for PR templates
TYPE_MAPPING = {
    "bug": "bug.md",
    "fix": "bug.md",
    "feature": "feature.md",
    "enhancement": "feature.md",
    "docs": "docs.md",
    "documentation": "docs.md",
    "refactor": "refactor.md",
    "cleanup": "refactor.md",
    "test": "test.md",
    "testing": "test.md",
    "performance": "performance.md",
    "optimization": "performance.md",
    "security": "security.md"
}


def run_git_command(args: list[str], cwd: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    """Run a git command with a timeout so MCP tool calls cannot hang indefinitely."""
    git_executable = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    repo_path = str(Path(cwd).resolve()).replace("\\", "/")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        [git_executable, "-c", f"safe.directory={repo_path}", "-C", repo_path, *args],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        text=True,
        check=True,
        cwd=Path(__file__).parent,
        env=env,
        timeout=timeout,
    )


# ===== Module 1 Tools (Already includes output limiting fix from Module 1) =====

@mcp.tool()
async def analyze_file_changes(
    base_branch: str = "main",
    include_diff: bool = True,
    max_diff_lines: int = 500,
    working_directory: Optional[str] = None
) -> str:
    """Get the full diff and list of changed files in the current git repository.

    Args:
        base_branch: Base branch to compare against (default: main)
        include_diff: Include the full diff content (default: true)
        max_diff_lines: Maximum number of diff lines to include (default: 500)
        working_directory: Directory to run git commands in (default: current directory)
    """
    try:
        if working_directory is None:
            try:
                context = mcp.get_context()
                roots_result = await asyncio.wait_for(
                    context.session.list_roots(),
                    timeout=2.0,
                )
                if roots_result.roots:
                    working_directory = roots_result.roots[0].uri.path
                    if len(working_directory) > 2 and working_directory[0] == "/" and working_directory[2] == ":":
                        working_directory = working_directory[1:]
            except Exception:
                pass

        cwd = working_directory if working_directory else os.getcwd()

        files_result = run_git_command(["diff", "--name-status", f"{base_branch}...HEAD"], cwd)
        stat_result = run_git_command(["diff", "--stat", f"{base_branch}...HEAD"], cwd)

        diff_content = ""
        truncated = False
        diff_lines = []
        if include_diff:
            diff_result = run_git_command(["diff", f"{base_branch}...HEAD"], cwd)
            diff_lines = diff_result.stdout.split('\n')
            if len(diff_lines) > max_diff_lines:
                diff_content = '\n'.join(diff_lines[:max_diff_lines])
                diff_content += f"\n\n... Output truncated. Showing {max_diff_lines} of {len(diff_lines)} lines ..."
                diff_content += "\n... Use max_diff_lines parameter to see more ..."
                truncated = True
            else:
                diff_content = diff_result.stdout

        commits_result = run_git_command(["log", "--oneline", f"{base_branch}..HEAD"], cwd)

        analysis = {
            "base_branch": base_branch,
            "files_changed": files_result.stdout,
            "statistics": stat_result.stdout,
            "commits": commits_result.stdout,
            "diff": diff_content if include_diff else "Diff not included (set include_diff=true to see full diff)",
            "truncated": truncated,
            "total_diff_lines": len(diff_lines) if include_diff else 0
        }

        return json.dumps(analysis, indent=2)

    except subprocess.CalledProcessError as e:
        return json.dumps({"error": f"Git error: {e.stderr}"})
    except subprocess.TimeoutExpired as e:
        return json.dumps({"error": "Git command timed out", "timeout_seconds": e.timeout})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_pr_templates() -> str:
    """List available PR templates with their content."""
    templates = [
        {
            "filename": filename,
            "type": template_type,
            "content": (TEMPLATES_DIR / filename).read_text()
        }
        for filename, template_type in DEFAULT_TEMPLATES.items()
    ]
    
    return json.dumps(templates, indent=2)


@mcp.tool()
async def suggest_template(changes_summary: str, change_type: str) -> str:
    """Let Claude analyze the changes and suggest the most appropriate PR template.
    
    Args:
        changes_summary: Your analysis of what the changes do
        change_type: The type of change you've identified (bug, feature, docs, refactor, test, etc.)
    """
    
    # Get available templates
    templates_response = await get_pr_templates()
    templates = json.loads(templates_response)
    
    # Find matching template
    template_file = TYPE_MAPPING.get(change_type.lower(), "feature.md")
    selected_template = next(
        (t for t in templates if t["filename"] == template_file),
        templates[0]  # Default to first template if no match
    )
    
    suggestion = {
        "recommended_template": selected_template,
        "reasoning": f"Based on your analysis: '{changes_summary}', this appears to be a {change_type} change.",
        "template_content": selected_template["content"],
        "usage_hint": "Claude can help you fill out this template based on the specific changes in your PR."
    }
    
    return json.dumps(suggestion, indent=2)


# ===== Module 2: New GitHub Actions Tools =====

@mcp.tool()
async def get_recent_actions_events(limit: int = 10) -> str:
    """Get recent GitHub Actions events received via webhook.
    
    Args:
        limit: Maximum number of events to return (default: 10)
    """
    if not EVENTS_FILE.exists():
        return json.dumps([])

    with open(EVENTS_FILE, "r") as f:
        events = json.load(f)

    limit = max(0, limit)
    return json.dumps(events[-limit:] if limit else [], indent=2)


@mcp.tool()
async def get_workflow_status(workflow_name: Optional[str] = None) -> str:
    """Get the current status of GitHub Actions workflows.
    
    Args:
        workflow_name: Optional specific workflow name to filter by
    """
    if not EVENTS_FILE.exists():
        return json.dumps([])

    with open(EVENTS_FILE, "r") as f:
        events = json.load(f)

    workflows = {}
    for event in events:
        run = event.get("workflow_run")
        if not run:
            continue

        name = run.get("name")
        if not name or (workflow_name and name != workflow_name):
            continue

        latest_time = run.get("updated_at") or event.get("timestamp") or ""
        if name in workflows and latest_time <= workflows[name]["updated_at"]:
            continue

        workflows[name] = {
            "name": name,
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "run_number": run.get("run_number"),
            "updated_at": latest_time,
            "html_url": run.get("html_url")
        }

    return json.dumps(list(workflows.values()), indent=2)


# ===== Module 2: MCP Prompts =====

@mcp.prompt()
async def analyze_ci_results():
    """Analyze recent CI/CD results and provide insights."""
    return """Analyze the recent CI/CD results from GitHub Actions.

Use these steps:
1. Call get_recent_actions_events() to fetch the latest webhook events.
2. Call get_workflow_status() to check the current state of each workflow.
3. Identify failed, cancelled, stale, or in-progress workflows.
4. Compare recent events with latest workflow status to spot patterns.
5. Provide concise, actionable next steps.

Format the response as:

## CI/CD Status Summary

### Overall Health
[Good, Warning, or Critical with a one-sentence reason]

### Latest Activity
- [Summarize the most important recent events]

### Workflow Status
- [Workflow name]: [status/conclusion] - [link if available]

### Issues Found
- [Failures, flaky behavior, blocked deployments, or no issues found]

### Recommended Actions
- [Specific next steps in priority order]"""


@mcp.prompt()
async def create_deployment_summary():
    """Generate a deployment summary for team communication."""
    return """Create a team-friendly deployment summary.

Use these steps:
1. Call get_workflow_status() to inspect current workflow results.
2. Focus on deployment, release, publish, and environment-specific workflows.
3. Use get_recent_actions_events() if more context is needed.
4. Summarize the outcome in plain language for teammates.

Format the response as a concise team update:

**Deployment Update**

- **Status**: [Success, Failed, In Progress, or Unknown]
- **Environment**: [Production, Staging, Development, or Unknown]
- **Workflow**: [Workflow name and run number if available]
- **When**: [Latest update time if available]
- **Link**: [Workflow URL if available]
- **Impact**: [User or team impact]
- **Next Steps**: [Required action, owner suggestion, or "None"]"""


@mcp.prompt()
async def generate_pr_status_report():
    """Generate a comprehensive PR status report including CI/CD results."""
    return """Generate a comprehensive PR status report that combines code changes and CI/CD state.

Use these steps:
1. Call analyze_file_changes() to understand the code changes.
2. Call get_workflow_status() to inspect CI/CD checks.
3. Call suggest_template() after identifying the likely change type.
4. Combine the results into a clear report for reviewers.

Format the response as:

## PR Status Report

### Code Changes
- **Files Modified**: [Summary by file or file type]
- **Change Type**: [Feature, Bug, Docs, Refactor, Test, Performance, or Security]
- **Impact**: [Low, Medium, or High with reasoning]
- **Key Changes**:
  - [Main change]
  - [Main change]

### CI/CD Status
- **Overall Checks**: [Passing, Failing, Running, or Unknown]
- **Workflows**:
  - [Workflow name]: [status/conclusion] - [link if available]
- **Failures or Risks**:
  - [Specific issue, or "None found"]

### PR Template Recommendation
- **Template**: [Recommended template]
- **Reason**: [Why it fits]

### Merge Readiness
- **Ready to Merge**: [Yes, No, or Needs Review]
- **Required Next Steps**:
  - [Action item]
  - [Action item]"""


@mcp.prompt()
async def troubleshoot_workflow_failure():
    """Help troubleshoot a failing GitHub Actions workflow."""
    return """Troubleshoot failing GitHub Actions workflows systematically.

Use these steps:
1. Call get_workflow_status() to identify failing workflows.
2. Call get_recent_actions_events() to inspect recent workflow events.
3. Determine whether the failure is new, recurring, or intermittent.
4. Connect the failure to recent code changes when possible.
5. Recommend a focused debugging path.

Format the response as:

## Workflow Troubleshooting Guide

### Failed Workflow Details
- **Workflow**: [Name]
- **Status**: [Status/conclusion]
- **Run**: [Run number and link if available]
- **Last Updated**: [Timestamp if available]
- **Failure Pattern**: [New, recurring, intermittent, or unknown]

### Likely Cause
[Best explanation based on available workflow events and recent changes]

### Diagnostics
- [Log, job, artifact, environment variable, dependency, or config to inspect]
- [Next diagnostic step]

### Suggested Fixes
- [Most likely fix]
- [Fallback fix]
- [Long-term prevention]

### Escalation Notes
- [Who or what system may need attention if the issue is outside the codebase]"""


if __name__ == "__main__":
    print("Starting PR Agent MCP server...")
    print("NOTE: Run webhook_server.py in a separate terminal to receive GitHub events")
    mcp.run()
