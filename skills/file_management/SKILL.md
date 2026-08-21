---
name: file_management
description: File operations — move, copy, rename, read, write, find files by name
tags: [file, sensitive]
risk: medium
origin: ai-pc-agent
---

# File Management Skill

## When to Activate

- User asks to move, copy, rename files
- User asks to find a file by name
- User asks to read, write, or edit files
- User asks to open a file with a specific application

## Core Concepts

### Tiered Operations

| Operation | Tier | Requires Confirmation |
|-----------|------|-----------------------|
| read_file | Safe | No |
| find_file | Safe | No |
| open_file | Safe | No |
| open_folder | Safe | No |
| copy_file | Sensitive | Yes (unless autonomy) |
| rename_file | Sensitive | Yes (unless autonomy) |
| move_file | Sensitive | Yes (unless autonomy) |
| write_file | Sensitive | Yes (unless autonomy) |
| append_file | Sensitive | Yes (unless autonomy) |
| edit_file_line | Sensitive | Yes (unless autonomy) |

### Path Resolution

Always expand `~` and `$VAR` before operating:
```python
path = os.path.expanduser(os.path.expandvars(path))
```

### Finding Files

Search in Desktop, Documents, Downloads, Pictures, Videos, Music, home, /tmp,
then expand outward. Skip `.cache`, `.var`, `.cargo`, `.rustup`, Trash.

## Anti-Patterns

### FAIL: Blind overwrite
Never overwrite without checking if destination exists in rename/move.

### FAIL: Unsanitized paths
Always expanduser/expandvars; never pass raw user input to shutil.

## Best Practices

- Return clear success/error messages with full resolved paths
- If a file doesn't exist, try find_file before giving up
- Log every action to audit_log for traceability
- Use shutil.copy2 to preserve metadata
