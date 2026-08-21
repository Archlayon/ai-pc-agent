---
name: gimp-automation
description: Automate GIMP workflows - actual GIMP batch operations via Script-Fu for poster design, image editing, filters, and exports with asset downloading
tags: [gimp, image, design, automation]
risk: medium
origin: ai-pc-agent
---

# GIMP Automation Skill

## When to Activate

- User asks to "edit in GIMP", "automate GIMP", "batch process images in GIMP"
- User asks to "apply filter", "resize images", "convert to PNG/JPEG in GIMP"
- User asks to "batch edit", "process multiple images", "apply GIMP filter"
- User asks to "design a poster", "create a poster", "make a poster", "make a flyer", "make a banner"
- User mentions GIMP in context of creating/editing images

## Important: This Uses Actual GIMP

- `create_poster` launches **actual GIMP** in non-interactive batch mode (`gimp -i` or `flatpak run org.gimp.GIMP -i`)
- GIMP creates the image, applies gradients, adds text layers, composites downloaded images
- The tool downloads any asset images from URLs first, then passes them to GIMP
- No Pillow or other libraries generate the final image - GIMP does all the work
- `create_poster` auto-shrinks the title in steps until it fits the canvas width (with a 40px margin). The agent should **not** pre-shrink text itself; just pass the natural title and let GIMP handle sizing.

## Workflow Rules

### For Poster / Flyer / Banner Design

When the user asks to **design/create/make a poster, flyer, or banner**:
1. Use `gimp_batch_operation` with `operation="create_poster"`
2. Pass `title`, `subtitle`, `width`, `height`, colors
3. Optionally pass `asset_urls` (list of image URLs to download and add as layers)
4. GIMP will create the poster programmatically with layers, text, and blended images
5. After creating, confirm the file was saved and show the path

### For Image Editing / Filters

When the user asks to edit an existing image:
1. Use `gimp_batch_operation` with the appropriate operation
2. Supported: resize, autolevel, grayscale, blur, sharpen, brightness_contrast, flip, rotate, convert_format

## Core Concepts

### Batch-Only Operation

- Always use `gimp -i` (no GUI) or `gimp-console-2.10` for automation
- Never try to control the GIMP GUI
- Always include `(gimp-quit 0)` at the end of batch scripts
- Set a timeout - GIMP batch jobs can hang on large images

### Supported Operations

| Operation | Description | Extra Params |
|-----------|-------------|--------------|
| `resize` | Resize image to exact dimensions | `width` (int), `height` (int) |
| `autolevel` | Auto-adjust levels | none |
| `grayscale` | Convert to grayscale | none |
| `blur` | Gaussian blur | `radius` (float, default 5.0) |
| `sharpen` | Unsharp mask sharpen | `amount` (float, default 50.0) |
| `brightness_contrast` | Adjust brightness and contrast | `brightness` (float), `contrast` (float) |
| `flip` | Flip horizontal or vertical | `direction` ("horizontal" or "vertical") |
| `rotate` | Rotate image | `rotation`: 90, 180, or 270 (enum, default 90) |
| `convert_format` | Convert image format | output path extension determines format |
| `create_poster` | Create a new poster image from scratch | `title` (str), `subtitle` (str), `width` (int), `height` (int), `background_color` (hex), `title_color` (hex), `subtitle_color` (hex), `font_size` (int), `subtitle_font_size` (int), `asset_urls` (list of str) |

### Safety Rules

- Only pre-defined operations are allowed - no arbitrary Scheme/Python-Fu code
- Input paths must exist before processing
- Output paths default to `<input>_gimp_<op><ext>` if not specified
- Failed asset downloads are skipped individually, not fatal - the poster still generates with whatever assets succeeded
- Timeout: 120s applies to the GIMP process itself; asset downloads (up to 30s each) happen separately beforehand and aren't counted against that limit

### Executable Discovery

- Auto-detects `gimp-console-2.10` first, then `gimp`, on Linux via `shutil.which()`
- If not on PATH, checks Flatpak for `org.gimp.GIMP`
- On Windows, checks common install paths under `C:\Program Files\GIMP*` and `C:\Program Files\GNU\GIMP*`
- If GIMP is not found, the tool returns `[error] GIMP is not installed or not in PATH.`
- If GIMP is found but the batch script fails, the error output from GIMP is included in the message for debugging

## Code Examples

```python
# Create a poster with actual GIMP
gimp_batch_operation("create_poster", output_path="~/Pictures/morning_coffee_poster.png",
    title="Morning Coffee", subtitle="Radio Show - Every Morning at 7AM",
    width=1080, height=1920, background_color="#1a1a2e",
    title_color="#ffffff", subtitle_color="#e94560")

# Create a poster with downloaded assets (coffee images, backgrounds)
gimp_batch_operation("create_poster",
    output_path="~/Downloads/coffee_show_poster.png",
    title="Morning Coffee",
    subtitle="Your Daily Brew of News & Music",
    width=1080, height=1920,
    asset_urls=[
        "https://example.com/coffee_cup.png",
        "https://example.com/sunrise_bg.jpg"
    ])

# Resize an existing image using GIMP
gimp_batch_operation("resize", "~/Pictures/photo.jpg", "~/Pictures/photo_small.jpg", width=800, height=600)
```

## Best Practices

- Validate image paths before calling GIMP
- Use descriptive output filenames to avoid overwriting originals
- Report GIMP availability if not installed
- Log all operations to audit_log with timestamps
