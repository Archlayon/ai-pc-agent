---
name: gimp-designer
description: Natural-language design agent for GIMP - creates posters, flyers, and banners from plain English requests with automatic asset downloading and composition
tags: [gimp, design, poster, flyer, banner, automation]
risk: medium
origin: ai-pc-agent
---

# GIMP Designer Agent

## When to Activate

- User asks to "design a poster", "create a poster", "make a poster"
- User asks to "design a flyer", "create a flyer", "make a flyer"
- User asks to "design a banner", "create a banner", "make a banner"
- User asks to "design with GIMP", "use GIMP to design"
- User asks for graphic design work

## Important: This Is an Agent, Not Just a Tool

- `design_with_gimp` is a high-level design agent that interprets natural language
- It plans the composition, downloads relevant assets, and orchestrates GIMP operations
- It uses `gimp_batch_operation` internally to execute the actual GIMP work
- The agent handles the full workflow from request to saved file

## Important: GIMP Version Compatibility

- **GIMP 2.x**: Full Script-Fu batch automation. The agent creates posters entirely inside GIMP with layers, text, and assets.
- **GIMP 3.x**: Script-Fu API has breaking changes. The agent creates the poster composition using Pillow, then **opens the result in GIMP** for viewing and further manual editing. GIMP is still physically launched and the file is opened in it.

## Workflow

### Standard Design Request

When the user asks for a poster/flyer/banner:
1. Call `design_with_gimp` with the user's natural language request
2. The agent will:
   - Detect the installed GIMP version
   - Extract title and subtitle from the request
   - Download relevant assets based on keywords (coffee, music, sunrise, etc.)
   - For GIMP 2.x: create the poster using Script-Fu batch inside GIMP
   - For GIMP 3.x: create the poster with Pillow, then open it in GIMP
   - Save to the requested path or ~/Downloads by default
3. Confirm the file path to the user

### Asset Strategy

The agent downloads assets based on keywords in the request:
- "coffee" → coffee cup icon
- "morning", "sunrise" → morning/sunrise background
- "music", "podcast" → music icon

Assets are scaled to canvas size and composited at 60% opacity as background layers.

### Title Extraction

The agent extracts titles from phrases like:
- "design a poster for a radio show called Morning Coffee" → title="Morning Coffee", subtitle="Radio Show"
- "create a flyer for a podcast called Tech Talk" → title="Tech Talk", subtitle="Podcast"
- "make a banner for morning coffee" → title="Morning Coffee", subtitle=""

## Supported Operations

The agent internally uses these GIMP operations:
- `create_poster` - main composition with background, text, and assets
- Asset downloading and layering
- Future: `resize`, `convert_format`, `blur`, `brightness_contrast` for post-processing

## Safety

- Always saves to a user-specified path or ~/Downloads
- Does not overwrite existing files without warning
- All downloads use timeout and error handling
- Failed downloads are skipped - poster still generates with remaining assets
