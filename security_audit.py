"""
Security self-audit for the AI PC Agent.

Scans the agent's own configuration, skills, and tool definitions for
common risk patterns: hardcoded secrets, mismatched risk tiers,
unsafe subprocess patterns, exposed credentials in skills.

This is the ECC AgentShield-inspired "scan the agent itself as an attack
surface" principle. Output is a JSON report that can be consumed by
CI or the tray icon.
"""
import json
import os
import re
import glob

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SECURITY_REPORT_PATH = os.path.expanduser("~/.local/share/ai-pc-agent/security_report.json")

# Patterns that indicate potential secrets/hardcoded credentials
SECRET_PATTERNS = [
    (r"AI\d{6}[A-Za-z0-9_-]{35}", "Possible Google API key"),
    (r"sk-[A-Za-z0-9]{20,}", "Possible OpenAI API key"),
    (r"ghp_[A-Za-z0-9]{36}", "Possible GitHub token"),
    (r"AKIA[A-Z0-9]{16}", "Possible AWS access key"),
    (r"-----BEGIN (?:RSA |EC |)PRIVATE KEY-----", "Possible private key"),
]


def scan_file(filepath: str) -> list[dict]:
    """Scan a single file for security issues.

    Returns a list of findings: {file, line, type, issue, severity}
    """
    findings = []

    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return findings

    rel_path = os.path.relpath(filepath, PROJECT_ROOT)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments and empty lines for most checks
        is_comment = stripped.startswith("#") or stripped.startswith("//")

        # Check for hardcoded secrets / API keys
        if not is_comment:
            for pattern, label in SECRET_PATTERNS:
                if re.search(pattern, stripped):
                    findings.append({
                        "file": rel_path,
                        "line": i,
                        "type": "hardcoded_secret",
                        "issue": label,
                        "severity": "critical",
                    })

        # Check for shell=True (unsafe subprocess pattern) — only flag actual calls
        if "shell=True" in stripped and not is_comment:
            if re.match(r".*subprocess\.(run|Popen|call|check_output).*shell=True", stripped):
                findings.append({
                    "file": rel_path,
                    "line": i,
                    "type": "unsafe_subprocess",
                    "issue": "subprocess called with shell=True — potential injection risk",
                    "severity": "high",
                })

        # Check for eval/exec usage
        if re.match(r"\s*(eval|exec)\s*\(", stripped) and not is_comment:
            findings.append({
                "file": rel_path,
                "line": i,
                "type": "unsafe_eval",
                "issue": "eval/exec usage detected — potential code injection",
                "severity": "high",
            })

        # Check for hardcoded file paths to sensitive locations
        # Skip lines that are pattern definitions (contain regex syntax or list elements)
        if re.search(r"/etc/(shadow|passwd)", stripped) and not is_comment:
            if "re.search" not in stripped and "re.compile" not in stripped and "[" not in stripped:
                findings.append({
                    "file": rel_path,
                    "line": i,
                    "type": "sensitive_path",
                    "issue": "Reference to sensitive system path",
                    "severity": "medium",
                })

    return findings


def verify_tier_consistency() -> list[dict]:
    """Check that tool_registry.py tier assignments match actual risk.

    Flags mismatches like write_file as TIER_SAFE.
    """
    findings = []
    tool_registry_path = os.path.join(PROJECT_ROOT, "tool_registry.py")

    if not os.path.exists(tool_registry_path):
        return findings

    risky_tools = {
        "write_file": "high",      # writes/overwrites files
        "append_file": "high",     # modifies files
        "edit_file_line": "high",  # modifies files
        "move_file": "high",       # moves files
        "rename_file": "medium",   # renames files
        "copy_file": "medium",     # copies files
        "shutdown_pc": "critical", # system shutdown
        "restart_pc": "critical",  # system restart
        "set_brightness": "medium",
        "set_volume": "medium",
        "download_file": "medium",
        "capture_webcam": "high",
    }

    try:
        with open(tool_registry_path, "r") as f:
            content = f.read()
    except OSError:
        return findings

    for tool_name, expected_risk in risky_tools.items():
        # Find the tier assignment in the TOOLS dict
        pattern = rf'"{tool_name}"\s*:\s*\{{.*?("tier":\s*(TIER_\w+))'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            assigned_tier = match.group(2)
            if assigned_tier == "TIER_SAFE" and expected_risk in ("high", "medium", "critical"):
                findings.append({
                    "file": "tool_registry.py",
                    "line": _find_line(content, match.start()),
                    "type": "tier_mismatch",
                    "issue": f"Tool '{tool_name}' is {assigned_tier} but should be higher risk",
                    "severity": "warning",
                })

    return findings


def _find_line(content: str, position: int) -> int:
    """Convert a character position to a 1-indexed line number."""
    return content[:position].count("\n") + 1


def scan_skills_for_leaks() -> list[dict]:
    """Scan skill Markdown files for embedded secrets or private paths."""
    findings = []
    skills_dir = os.path.join(PROJECT_ROOT, "skills")

    for filepath in glob.glob(os.path.join(skills_dir, "**", "SKILL.md"), recursive=True):
        rel_path = os.path.relpath(filepath, PROJECT_ROOT)
        try:
            with open(filepath, "r") as f:
                content = f.read()
        except OSError:
            continue

        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, content):
                findings.append({
                    "file": rel_path,
                    "line": 0,
                    "type": "skill_leak",
                    "issue": f"Skill file contains {label.lower()}",
                    "severity": "critical",
                })

        # Check for absolute user paths that shouldn't be in skills
        if re.search(r"/home/\w+|/Users/\w+", content):
            findings.append({
                "file": rel_path,
                "line": 0,
                "type": "skill_hardcoded_path",
                "issue": "Skill contains hardcoded user paths — should be generic",
                "severity": "medium",
            })

    return findings


def run_full_audit() -> dict:
    """Run all security checks and return a complete report.

    Returns a dict with: summary, findings, generated_at.
    """
    all_findings = []

    # Scan Python source files (exclude self and audit/trace modules
    # whose pattern-detection strings would trigger false positives)
    audit_self = os.path.basename(__file__)
    for py_file in glob.glob(os.path.join(PROJECT_ROOT, "*.py")):
        if os.path.basename(py_file) in (audit_self, "trace_manager.py"):
            continue
        all_findings.extend(scan_file(py_file))

    # Scan tools/ directory
    tools_dir = os.path.join(PROJECT_ROOT, "tools")
    if os.path.isdir(tools_dir):
        for py_file in glob.glob(os.path.join(tools_dir, "**", "*.py"), recursive=True):
            all_findings.extend(scan_file(py_file))

    # Scan agents/ directory
    agents_dir = os.path.join(PROJECT_ROOT, "agents")
    if os.path.isdir(agents_dir):
        for py_file in glob.glob(os.path.join(agents_dir, "**", "*.py"), recursive=True):
            all_findings.extend(scan_file(py_file))

    # Verify tier consistency
    all_findings.extend(verify_tier_consistency())

    # Scan skills for leaks
    all_findings.extend(scan_skills_for_leaks())

    # Count by severity
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "warning": 0, "info": 0}
    for f in all_findings:
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    report = {
        "generated_at": datetime_now_iso(),
        "summary": {
            "total_findings": len(all_findings),
            **severity_counts,
        },
        "findings": all_findings,
    }

    # Write report
    os.makedirs(os.path.dirname(SECURITY_REPORT_PATH), exist_ok=True)
    tmp = SECURITY_REPORT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, SECURITY_REPORT_PATH)

    return report


def datetime_now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def print_report():
    """Print a human-readable summary of the security audit."""
    report = run_full_audit()
    summary = report["summary"]

    print(f"Security Audit Report — {report['generated_at']}")
    print(f"  Total findings: {summary['total_findings']}")

    for sev in ("critical", "high", "medium", "warning"):
        count = summary.get(sev, 0)
        if count > 0:
            label = "✗" if sev in ("critical", "high") else "!"
            print(f"  {label} {sev}: {count}")

    if summary["total_findings"] == 0:
        print("  All clear — no issues found.")
    else:
        print("\n  Details:")
        for f in report["findings"][:10]:
            print(f"    [{f['severity']}] {f['file']}:{f['line']} — {f['issue']}")
        if len(report["findings"]) > 10:
            print(f"    ... and {len(report['findings']) - 10} more")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI PC Agent security self-audit")
    parser.add_argument("--json", action="store_true", help="Output JSON report only")
    args = parser.parse_args()

    if args.json:
        report = run_full_audit()
        print(json.dumps(report, indent=2))
    else:
        print_report()
