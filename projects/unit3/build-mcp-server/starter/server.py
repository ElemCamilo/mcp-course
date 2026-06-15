#!/usr/bin/env python3
"""
Module 1: Basic MCP Server - Starter Code
TODO: Implement tools for analyzing git changes and suggesting PR templates
"""

import json
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Initialize the FastMCP server
mcp = FastMCP("pr-agent")

# PR template directory (shared across all modules)
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

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
    "security": "security.md",
}

@mcp.tool()
async def analyze_file_changes(
    base_branch: str = "main",
    include_diff: bool = True,
    max_diff_lines: int = 500,
) -> str:
    """Get the full diff and list of changed files in the current git repository.
    
    Args:
        base_branch: Base branch to compare against (default: main)
        include_diff: Include the full diff content (default: true)
        max_diff_lines: Maximum number of diff lines to include (default: 500)
    """
    cwd = Path.cwd()
    try:
        context = mcp.get_context()
        roots_result = await context.session.list_roots()
        if roots_result.roots:
            root_path = str(roots_result.roots[0].uri.path)
            if len(root_path) > 2 and root_path[0] == "/" and root_path[2] == ":":
                root_path = root_path[1:]
            cwd = Path(root_path)
    except Exception:
        pass

    comparison = f"{base_branch}...HEAD"

    try:
        files_result = subprocess.run(
            ["git", "diff", "--name-status", comparison],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        stat_result = subprocess.run(
            ["git", "diff", "--stat", comparison],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        commits_result = subprocess.run(
            ["git", "log", "--oneline", f"{base_branch}..HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

        files = []
        for line in files_result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                files.append({"status": parts[0], "path": parts[-1]})

        diff_content = ""
        total_diff_lines = 0
        truncated = False
        if include_diff:
            diff_result = subprocess.run(
                ["git", "diff", comparison],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            diff_lines = diff_result.stdout.splitlines()
            total_diff_lines = len(diff_lines)
            if total_diff_lines > max_diff_lines:
                diff_content = "\n".join(diff_lines[:max_diff_lines])
                diff_content += (
                    f"\n\n... Output truncated. Showing {max_diff_lines} "
                    f"of {total_diff_lines} lines ..."
                )
                truncated = True
            else:
                diff_content = diff_result.stdout

        return json.dumps(
            {
                "base_branch": base_branch,
                "comparison": comparison,
                "working_directory": str(cwd),
                "files_changed": files_result.stdout,
                "files": files,
                "statistics": stat_result.stdout,
                "commits": commits_result.stdout,
                "diff": diff_content if include_diff else "Diff not included",
                "truncated": truncated,
                "total_diff_lines": total_diff_lines,
            },
            indent=2,
        )
    except subprocess.CalledProcessError as exc:
        return json.dumps({"error": f"Git error: {exc.stderr or exc}"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
async def get_pr_templates() -> str:
    """List available PR templates with their content."""
    templates = [
        {
            "filename": template_path.name,
            "type": template_path.stem.replace("-", " ").replace("_", " ").title(),
            "content": template_path.read_text(encoding="utf-8"),
        }
        for template_path in sorted(TEMPLATES_DIR.glob("*.md"))
    ]

    return json.dumps(templates, indent=2)


@mcp.tool()
async def suggest_template(changes_summary: str, change_type: str) -> str:
    """Suggest the most appropriate PR template for the provided change type.
    
    Args:
        changes_summary: Your analysis of what the changes do
        change_type: The type of change you've identified (bug, feature, docs, refactor, test, etc.)
    """
    templates_response = await get_pr_templates()
    templates = json.loads(templates_response)

    template_file = TYPE_MAPPING.get(change_type.lower(), "feature.md")
    selected_template = next(
        (template for template in templates if template["filename"] == template_file),
        templates[0],
    )

    suggestion = {
        "recommended_template": selected_template,
        "reasoning": (
            f"Based on your analysis: '{changes_summary}', this appears to be "
            f"a {change_type} change."
        ),
        "template_content": selected_template["content"],
        "usage_hint": (
            "Use this template with Codex to fill it out based on the specific "
            "changes in your PR."
        ),
    }

    return json.dumps(suggestion, indent=2)


if __name__ == "__main__":
    mcp.run()
