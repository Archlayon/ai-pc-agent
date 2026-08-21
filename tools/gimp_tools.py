"""
GIMP automation tools for the AI PC Agent.

Wraps GIMP batch operations via gimp-console-2.10 / gimp -i.
Only pre-defined, safe operations are allowed — no arbitrary code execution.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse

from audit_log import log_action


GIMP_BIN = "gimp"
GIMP_CONSOLE = "gimp-console-2.10"
TIMEOUT = 120


def _find_gimp() -> str | None:
    for name in (GIMP_CONSOLE, GIMP_BIN):
        if shutil.which(name):
            return name
    if os.name == "nt":
        for base in [r"C:\Program Files", r"C:\Program Files (x86)"]:
            if os.path.isdir(base):
                for entry in os.listdir(base):
                    if entry.lower().startswith("gimp"):
                        gimp_exe = os.path.join(base, entry, "bin", "gimp-2.10.exe")
                        if os.path.isfile(gimp_exe):
                            return gimp_exe
                        gimp_exe = os.path.join(base, entry, "bin", "gimp.exe")
                        if os.path.isfile(gimp_exe):
                            return gimp_exe
    try:
        import subprocess
        result = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True, timeout=10)
        if "org.gimp.GIMP" in result.stdout:
            return "flatpak"
    except Exception:
        pass
    return None


def _get_gimp_version() -> tuple[int, int]:
    """Return (major, minor) version of installed GIMP, or (0, 0) if not found."""
    gimp = _find_gimp()
    if not gimp:
        return (0, 0)
    try:
        if gimp == "flatpak":
            cmd = ["flatpak", "run", "org.gimp.GIMP", "--version"]
        else:
            cmd = [gimp, "--version"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr
        match = re.search(r"(\d+)\.(\d+)", output)
        if match:
            return (int(match.group(1)), int(match.group(2)))
    except Exception:
        pass
    return (0, 0)


def _escape_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def _run_gimp_batch(script: str, timeout: int = TIMEOUT) -> tuple[bool, str]:
    """Run a Script-Fu batch script in GIMP non-interactive mode.

    The timeout applies only to the GIMP process itself. Any asset downloads
    happen beforehand and are not counted against this limit.
    """
    gimp = _find_gimp()
    if not gimp:
        return False, "GIMP is not installed or not in PATH."

    with tempfile.NamedTemporaryFile(mode="w", suffix=".scm", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        if gimp == "flatpak":
            cmd = ["flatpak", "run", "org.gimp.GIMP", "-i", "--batch-interpreter=plug-in-script-fu-eval", "-b", f'(load "{script_path}")', "-b", "(gimp-quit 0)"]
        else:
            cmd = [gimp, "-i", "--batch-interpreter=plug-in-script-fu-eval", "-b", f'(load "{script_path}")', "-b", "(gimp-quit 0)"]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = proc.stdout + proc.stderr
        success = proc.returncode == 0
        return success, output
    except subprocess.TimeoutExpired:
        return False, "GIMP batch operation timed out."
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _resize_image(input_path: str, output_path: str, width: int, height: int) -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-resize in_path out_path new_w new_h)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-image-scale img new_w new_h)
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-resize "{ip}" "{op}" {width} {height})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Resized image saved to {output_path}"
    return f"[error] Resize failed: {msg}"


def _autolevel_image(input_path: str, output_path: str) -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-autolevel in_path out_path)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-levels-auto drawable)
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-autolevel "{ip}" "{op}")
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Auto-level applied. Saved to {output_path}"
    return f"[error] Auto-level failed: {msg}"


def _grayscale_image(input_path: str, output_path: str) -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-grayscale in_path out_path)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-image-convert-grayscale img)
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-grayscale "{ip}" "{op}")
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Converted to grayscale. Saved to {output_path}"
    return f"[error] Grayscale failed: {msg}"


def _blur_image(input_path: str, output_path: str, radius: float = 5.0) -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-blur in_path out_path rad)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (plug-in-gauss RUN-NONINTERACTIVE img drawable rad rad 0)
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-blur "{ip}" "{op}" {radius})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Blurred (radius={radius}). Saved to {output_path}"
    return f"[error] Blur failed: {msg}"


def _sharpen_image(input_path: str, output_path: str, amount: float = 50.0) -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-sharpen in_path out_path amt)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (plug-in-unsharp-mask RUN-NONINTERACTIVE img drawable 5.0 {amount} 0)
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-sharpen "{ip}" "{op}" {amount})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Sharpened (amount={amount}). Saved to {output_path}"
    return f"[error] Sharpen failed: {msg}"


def _brightness_contrast_image(
    input_path: str, output_path: str, brightness: float = 0.0, contrast: float = 0.0
) -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-brightness-contrast in_path out_path bri con)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-brightness-contrast drawable {brightness} {contrast})
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-brightness-contrast "{ip}" "{op}" {brightness} {contrast})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Brightness/contrast adjusted. Saved to {output_path}"
    return f"[error] Brightness/contrast failed: {msg}"


def _flip_image(input_path: str, output_path: str, direction: str = "horizontal") -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    axis = "TRUE" if direction.lower().startswith("h") else "FALSE"
    script = f"""
(define (batch-flip in_path out_path horiz)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-image-flip img {axis})
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-flip "{ip}" "{op}" {axis})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Flipped {direction}. Saved to {output_path}"
    return f"[error] Flip failed: {msg}"


def _rotate_image(input_path: str, output_path: str, degrees: int = 90) -> str:
    valid = {90, 180, 270}
    if degrees not in valid:
        return f"[error] Unsupported rotation: {degrees}. Only 90, 180, and 270 are supported."
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    script = f"""
(define (batch-rotate in_path out_path deg)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-image-rotate img 0 {degrees})
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-rotate "{ip}" "{op}" {degrees})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Rotated {degrees} degrees. Saved to {output_path}"
    return f"[error] Rotate failed: {msg}"


def _convert_format_image(input_path: str, output_path: str, format_hint: str = "") -> str:
    ip = _escape_path(input_path)
    op = _escape_path(output_path)
    ext = os.path.splitext(output_path)[1].lower().lstrip(".")
    script = f"""
(define (batch-convert in_path out_path)
  (let* (
    (img (car (gimp-file-load RUN-NONINTERACTIVE in_path in_path)))
    (drawable (car (gimp-image-get-layers img)))
  )
    (gimp-file-save RUN-NONINTERACTIVE img out_path drawable)
    (gimp-image-delete img)
  )
)
(batch-convert "{ip}" "{op}")
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Converted to {ext.upper()}. Saved to {output_path}"
    return f"[error] Format conversion failed: {msg}"


def _download_image(url: str, dest_path: str) -> str:
    """Download an image from a URL to a local path."""
    import requests
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp.raise_for_status()
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return dest_path
    except Exception as e:
        return f"[error] Download failed: {e}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (255, 255, 255)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _create_poster(
    output_path: str,
    title: str = "",
    subtitle: str = "",
    width: int = 1080,
    height: int = 1920,
    background_color: str = "#1a1a2e",
    title_color: str = "#ffffff",
    subtitle_color: str = "#e94560",
    font_size: int = 80,
    subtitle_font_size: int = 40,
    asset_urls: list[str] | None = None,
) -> str:
    """Create a poster. Uses actual GIMP Script-Fu for GIMP 2.x.
    For GIMP 3.x (which has Script-Fu API breaks), falls back to Pillow
    for composition and opens the result in GIMP."""
    gimp = _find_gimp()
    if not gimp:
        return "[error] GIMP is not installed or not in PATH."

    output_path = os.path.expanduser(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    major, minor = _get_gimp_version()

    if major >= 3:
        return _create_poster_gimp3(
            output_path=output_path,
            title=title,
            subtitle=subtitle,
            width=width,
            height=height,
            background_color=background_color,
            title_color=title_color,
            subtitle_color=subtitle_color,
            font_size=font_size,
            subtitle_font_size=subtitle_font_size,
            asset_urls=asset_urls,
            gimp=gimp,
        )

    bg_r, bg_g, bg_b = _hex_to_rgb(background_color)
    title_r, title_g, title_b = _hex_to_rgb(title_color)
    sub_r, sub_g, sub_b = _hex_to_rgb(subtitle_color)

    asset_paths = []
    if asset_urls:
        for idx, url in enumerate(asset_urls):
            ext = os.path.splitext(urlparse(url).path)[1].lower() or ".png"
            dest = os.path.join(tempfile.gettempdir(), f"gimp_asset_{int(time.time())}_{idx}{ext}")
            result = _download_image(url, dest)
            if result.startswith("[error]"):
                continue
            asset_paths.append(result)

    auto_font_size = font_size
    if title and width > 80:
        try:
            from PIL import ImageFont as _PILFont
            try:
                _font = _PILFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except Exception:
                _font = _PILFont.load_default()
            _dummy = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).ImageDraw.Draw(__import__("PIL.Image", fromlist=["Image"]).new("RGB", (1, 1)))
            max_w = width - 80
            while auto_font_size > 12:
                bbox = _dummy.textbbox((0, 0), title, font=_font)
                if bbox[2] - bbox[0] <= max_w:
                    break
                auto_font_size = int(auto_font_size * 0.9)
                try:
                    _font = _PILFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", auto_font_size)
                except Exception:
                    _font = _PILFont.load_default()
        except Exception:
            pass

    asset_layer_lines = ""
    for asset_path in asset_paths:
        ap = _escape_path(asset_path)
        asset_layer_lines += f"""
  (let* (
    (asset-layer (car (gimp-file-load-layer RUN-NONINTERACTIVE "{ap}")))
  )
    (gimp-image-add-layer img asset-layer 0)
    (gimp-layer-scale asset-layer {width} {height})
    (gimp-layer-set-opacity asset-layer 60)
  )
"""

    script = f"""
(define (create-poster out_path w h bg-r bg-g bg-b title-text sub-text title-size sub-size title-r title-g title-b sub-r sub-g sub-b)
  (let* (
    (img (car (gimp-image-new w h RGB)))
    (bg-layer (car (gimp-layer-new w h RGB-IMAGE "Background" 100 NORMAL-MODE)))
    (title-layer (car (gimp-text-font-new img "Sans Bold" title-size 0 title-text 0 0 TRUE TRUE 0)))
    (sub-layer (car (gimp-text-font-new img "Sans" sub-size 0 sub-text 0 0 TRUE TRUE 0)))
  )
    (gimp-image-add-layer img bg-layer 0)
    (gimp-drawable-fill bg-layer BACKGROUND-FILL)
    (gimp-image-add-layer img title-layer 0)
    (gimp-image-add-layer img sub-layer 0)
    (gimp-layer-translate title-layer (/ (- w (car (gimp-drawable-width title-layer))) 2) (/ (* h 35) 100))
    (gimp-layer-translate sub-layer (/ (- w (car (gimp-drawable-width sub-layer))) 2) (/ (* h 55) 100))
    (gimp-context-set-foreground (list title-r title-g title-b))
    (gimp-drawable-fill title-layer FOREGROUND-FILL)
    (gimp-context-set-foreground (list sub-r sub-g sub-b))
    (gimp-drawable-fill sub-layer FOREGROUND-FILL)
{asset_layer_lines}
    (gimp-image-undo-group-start img)
    (gimp-image-flatten img)
    (gimp-image-undo-group-end img)
    (gimp-file-save RUN-NONINTERACTIVE img out_path (car (gimp-image-get-layers img)))
    (gimp-image-delete img)
  )
)
(create-poster "{_escape_path(output_path)}" {width} {height} {bg_r} {bg_g} {bg_b} "{_escape_path(title)}" "{_escape_path(subtitle)}" {auto_font_size} {subtitle_font_size} {title_r} {title_g} {title_b} {sub_r} {sub_g} {sub_b})
(gimp-quit 0)
"""
    ok, msg = _run_gimp_batch(script)
    if ok and os.path.exists(output_path):
        return f"Poster created in GIMP and saved to {output_path}"
    return f"[error] GIMP poster creation failed: {msg}"


def _create_poster_gimp3(
    output_path: str,
    title: str = "",
    subtitle: str = "",
    width: int = 1080,
    height: int = 1920,
    background_color: str = "#1a1a2e",
    title_color: str = "#ffffff",
    subtitle_color: str = "#e94560",
    font_size: int = 80,
    subtitle_font_size: int = 40,
    asset_urls: list[str] | None = None,
    gimp: str = "flatpak",
) -> str:
    """Create a poster for GIMP 3.x using Pillow, then open in GIMP."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return "[error] Pillow is not installed. Cannot create poster for GIMP 3.x. Install with: pip install Pillow"

    output_path = os.path.expanduser(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (width, height), background_color)
        draw = ImageDraw.Draw(img)

        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", subtitle_font_size)
        except Exception:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()

        if title:
            bbox = draw.textbbox((0, 0), title, font=font_title)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x = (width - tw) / 2
            y = height * 0.35
            draw.text((x, y), title, fill=title_color, font=font_title)

        if subtitle:
            bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x = (width - tw) / 2
            y = height * 0.55
            draw.text((x, y), subtitle, fill=subtitle_color, font=font_sub)

        if asset_urls:
            for idx, url in enumerate(asset_urls):
                ext = os.path.splitext(urlparse(url).path)[1].lower() or ".png"
                dest = os.path.join(tempfile.gettempdir(), f"gimp3_asset_{int(time.time())}_{idx}{ext}")
                result = _download_image(url, dest)
                if result.startswith("[error]"):
                    continue
                try:
                    asset = Image.open(result).convert("RGBA")
                    asset = asset.resize((width, height), Image.Resampling.LANCZOS)
                    img.paste(asset, (0, 0), asset)
                except Exception:
                    pass

        img.save(output_path, quality=95)
    except Exception as e:
        return f"[error] Failed to create poster: {e}"

    try:
        _open_in_gimp(output_path, gimp)
        return f"Poster created and opened in GIMP. Saved to {output_path}"
    except Exception as e:
        return f"Poster created and saved to {output_path}. (Could not open in GIMP: {e})"


def _open_in_gimp(path: str, gimp: str = "flatpak") -> None:
    """Open an image in GIMP."""
    path = os.path.expanduser(path)
    if gimp == "flatpak":
        subprocess.Popen(
            ["flatpak", "run", "org.gimp.GIMP", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        subprocess.Popen(
            [gimp, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (255, 255, 255)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


SUPPORTED_OPERATIONS = {
    "resize": _resize_image,
    "autolevel": _autolevel_image,
    "grayscale": _grayscale_image,
    "blur": _blur_image,
    "sharpen": _sharpen_image,
    "brightness_contrast": _brightness_contrast_image,
    "flip": _flip_image,
    "rotate": _rotate_image,
    "convert_format": _convert_format_image,
    "create_poster": _create_poster,
}


def gimp_batch_operation(
    operation: str,
    input_path: str = "",
    output_path: str = "",
    **params,
) -> str:
    """Run a GIMP batch operation on an image or create a new poster.

    Supported operations: resize, autolevel, grayscale, blur, sharpen,
    brightness_contrast, flip, rotate, convert_format, create_poster.

    For resize: pass width (int) and height (int).
    For blur: pass radius (float, default 5.0).
    For sharpen: pass amount (float, default 50.0).
    For brightness_contrast: pass brightness (float, default 0.0) and contrast (float, default 0.0).
    For flip: pass direction ("horizontal" or "vertical").
    For rotate: pass rotation (int, one of 90, 180, 270; default 90).
    For create_poster: pass title (str), subtitle (str), width (int), height (int), background_color (str), title_color (str), subtitle_color (str), asset_urls (list of str, optional).
    """
    op = operation.strip().lower().replace(" ", "_").replace("-", "_")
    if op not in SUPPORTED_OPERATIONS:
        return (
            f"[error] Unsupported GIMP operation: {operation}. "
            f"Supported: {', '.join(sorted(SUPPORTED_OPERATIONS))}"
        )

    if op == "create_poster":
        if not output_path:
            output_path = os.path.join(os.path.expanduser("~/Pictures"), f"poster_{int(time.time())}.png")
        return _create_poster(output_path=output_path, **params)

    input_path = os.path.expanduser(input_path)
    if not input_path or not os.path.exists(input_path):
        return f"[error] Input file not found: {input_path}"

    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_gimp_{op}{ext}"
    else:
        output_path = os.path.expanduser(output_path)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    func = SUPPORTED_OPERATIONS[op]
    result = func(input_path, output_path, **params)
    log_action("gimp_batch_operation", {"operation": op, "input": input_path, "output": output_path, "params": params}, "approved", result)
    return result
