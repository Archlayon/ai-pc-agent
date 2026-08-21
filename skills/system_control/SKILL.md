---
name: system_control
description: PC system operations — brightness, volume, shutdown, restart, media playback
tags: [system, high-risk]
risk: high
origin: ai-pc-agent
---

# System Control Skill

## When to Activate

- User asks to change brightness or volume
- User asks to shut down, restart, or cancel shutdown
- User asks to play media
- User asks about battery, CPU, memory, or disk status

## Core Concepts

### Tiered Operations

| Operation | Tier | Confirmation |
|-----------|------|-------------|
| get_battery_status | Safe | No |
| get_cpu_usage | Safe | No |
| get_memory_usage | Safe | No |
| get_disk_usage | Safe | No |
| get_full_pc_state | Safe | No |
| get_brightness | Safe | No |
| get_volume | Safe | No |
| set_brightness | Sensitive | Yes |
| set_volume | Sensitive | Yes |
| play_media | Safe | No |
| cancel_shutdown | Sensitive | Yes |
| shutdown_pc | High-Risk | Type "shutdown_pc" exactly |
| restart_pc | High-Risk | Type "restart_pc" exactly |

### High-Risk Confirmation

High-risk actions (shutdown, restart) require the user to type the exact tool
name to confirm. This cannot be bypassed by autonomy mode.

### Webcam (On-Demand Only)

- Webcam is accessed only when explicitly requested
- Never runs silently in the background
- User must confirm each capture

## Best Practices

- Always show battery/CPU/disk status before recommending a restart
- Default brightness/volume changes require confirmation even in autonomy mode
- Log all system changes to audit_log with timestamps
- Cancel pending shutdowns automatically if user cancels
