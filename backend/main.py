import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
MEDIA_DIR = ROOT / "media"
MEDIA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="LightnoteAI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


def understand_prompt(prompt: str) -> dict:
    """Use Gemini when configured, with a deterministic parser for local demos."""
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=(
                    "Return only JSON with operation, target, and replacement. "
                    "operation must be replace_object or remove_object. Prompt: " + prompt
                ),
                config={"response_mime_type": "application/json"},
            )
            parsed = json.loads(response.text)
            return parsed
        except Exception as error:
            print(f"Gemini unavailable, using local parser: {error}")

    removal = re.search(r"remove (?:the )?(.+?)[.]?$", prompt, re.IGNORECASE)
    replacement = re.search(
        r"replace (?:the )?(.+?) (?:with|by) (.+?)[.]?$", prompt, re.IGNORECASE
    )
    if removal:
        return {
            "operation": "remove_object",
            "target": removal.group(1).strip(),
            "replacement": "background reconstruction",
        }
    if replacement:
        return {
            "operation": "replace_object",
            "target": replacement.group(1).strip(),
            "replacement": replacement.group(2).strip(),
        }
    return {
        "operation": "replace_object",
        "target": "the specified object",
        "replacement": "the requested replacement",
    }


def locate_target_with_gemini(source: Path, target: str) -> list[float] | None:
    """Ask Gemini vision for a normalized [x, y, width, height] target box."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    capture = cv2.VideoCapture(str(source))
    success, frame = capture.read()
    capture.release()
    if not success:
        return None
    success, encoded = cv2.imencode(".jpg", frame)
    if not success:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=encoded.tobytes(), mime_type="image/jpeg"),
                f"Find the object described as '{target}'. Return only JSON with box as normalized [x, y, width, height] values from 0 to 1. If not visible, return box null.",
            ],
            config={"response_mime_type": "application/json"},
        )
        box = json.loads(response.text).get("box")
        if isinstance(box, list) and len(box) == 4:
            return [max(0, min(1, float(value))) for value in box]
    except Exception as error:
        print(f"Gemini vision localization unavailable: {error}")
    return None


def render_video(source: Path, output: Path, reference: Path | None, interpretation: dict, target_box: list[float] | None) -> None:
    """Track the target box with OpenCV and composite the reference into it."""
    if not reference or interpretation["operation"] != "replace_object":
        command = ["ffmpeg", "-y", "-i", str(source), "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-1200:])
        return
    if not target_box:
        raise ValueError("Target not found. Add a Gemini API key or draw a target box on the first frame.")
    if len(target_box) != 4 or any(value < 0 or value > 1 for value in target_box) or target_box[2] <= 0 or target_box[3] <= 0:
        raise ValueError("Target box must contain normalized x, y, width, and height values.")

    capture = cv2.VideoCapture(str(source))
    success, first_frame = capture.read()
    if not success:
        capture.release()
        raise ValueError("Could not read the first video frame.")
    frame_height, frame_width = first_frame.shape[:2]
    x, y, width, height = target_box
    initial_box = (int(x * frame_width), int(y * frame_height), int(width * frame_width), int(height * frame_height))
    initial_box = (max(0, initial_box[0]), max(0, initial_box[1]), max(2, initial_box[2]), max(2, initial_box[3]))
    tracker_factory = getattr(cv2, "TrackerCSRT_create", None)
    if tracker_factory is None and hasattr(cv2, "legacy"):
        tracker_factory = getattr(cv2.legacy, "TrackerCSRT_create", None)
    tracker = tracker_factory() if tracker_factory else None
    if tracker:
        tracker.init(first_frame, initial_box)
    template = cv2.cvtColor(first_frame[initial_box[1]:initial_box[1] + initial_box[3], initial_box[0]:initial_box[0] + initial_box[2]], cv2.COLOR_BGR2GRAY)
    reference_image = cv2.imread(str(reference), cv2.IMREAD_UNCHANGED)
    if reference_image is None:
        capture.release()
        raise ValueError("Could not read the reference image.")
    if reference_image.shape[2] == 4:
        reference_image = cv2.cvtColor(reference_image, cv2.COLOR_BGRA2BGR)
    reference_image = extract_reference_foreground(reference_image)
    temp_video = output.with_name("video-only.mp4")
    writer = cv2.VideoWriter(str(temp_video), cv2.VideoWriter_fourcc(*"mp4v"), capture.get(cv2.CAP_PROP_FPS) or 24, (frame_width, frame_height))
    current_box = initial_box
    first_pass = True
    while True:
        if not success:
            break
        if not first_pass:
            if tracker:
                tracked, tracked_box = tracker.update(first_frame)
            else:
                tracked, tracked_box = match_target_template(first_frame, template, current_box)
            if tracked:
                candidate_box = tuple(int(value) for value in tracked_box)
                previous_center = (current_box[0] + current_box[2] / 2, current_box[1] + current_box[3] / 2)
                candidate_center = (candidate_box[0] + candidate_box[2] / 2, candidate_box[1] + candidate_box[3] / 2)
                center_motion = ((candidate_center[0] - previous_center[0]) ** 2 + (candidate_center[1] - previous_center[1]) ** 2) ** 0.5
                size_ratio = candidate_box[2] / max(1, current_box[2])
                max_motion = max(frame_width, frame_height) * 0.12
                if center_motion <= max_motion and 0.65 <= size_ratio <= 1.5:
                    current_box = candidate_box
        first_pass = False
        box_x, box_y, box_width, box_height = current_box
        box_x = max(0, min(frame_width - 1, box_x))
        box_y = max(0, min(frame_height - 1, box_y))
        box_width = max(2, min(frame_width - box_x, box_width))
        box_height = max(2, min(frame_height - box_y, box_height))
        roi_padding = max(4, min(box_width, box_height) // 8)
        roi_x = max(0, box_x - roi_padding)
        roi_y = max(0, box_y - roi_padding)
        roi_right = min(frame_width, box_x + box_width + roi_padding)
        roi_bottom = min(frame_height, box_y + box_height + roi_padding)
        roi = first_frame[roi_y:roi_bottom, roi_x:roi_right].copy()
        roi_mask = np.zeros(roi.shape[:2], dtype=np.uint8)
        roi_mask[box_y - roi_y:box_y - roi_y + box_height, box_x - roi_x:box_x - roi_x + box_width] = 255
        cleaned_roi = cv2.inpaint(roi, roi_mask, 3, cv2.INPAINT_TELEA)
        cleaned_frame = first_frame.copy()
        cleaned_frame[roi_y:roi_bottom, roi_x:roi_right] = cleaned_roi
        replacement = cv2.resize(reference_image, (box_width, box_height), interpolation=cv2.INTER_LANCZOS4)
        replacement_rgb = replacement[:, :, :3]
        replacement_alpha = replacement[:, :, 3:4] / 255.0
        target_area = cleaned_frame[box_y:box_y + box_height, box_x:box_x + box_width]
        blended = (replacement_rgb * replacement_alpha + target_area * (1 - replacement_alpha)).astype(np.uint8)
        blurred = cv2.GaussianBlur(blended, (0, 0), 1.0)
        blended = cv2.addWeighted(blended, 1.35, blurred, -0.35, 0)
        cleaned_frame[box_y:box_y + box_height, box_x:box_x + box_width] = blended
        writer.write(cleaned_frame)
        success, first_frame = capture.read()
    capture.release()
    writer.release()
    command = ["ffmpeg", "-y", "-i", str(temp_video), "-i", str(source), "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    temp_video.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:])


def match_target_template(frame: np.ndarray, template: np.ndarray, previous_box: tuple[int, int, int, int]) -> tuple[bool, tuple[int, int, int, int]]:
    """Find the selected object's visual patch near its last known position."""
    frame_height, frame_width = frame.shape[:2]
    x, y, width, height = previous_box
    padding_x, padding_y = max(width * 2, 40), max(height * 2, 40)
    left, top = max(0, int(x - padding_x)), max(0, int(y - padding_y))
    right, bottom = min(frame_width, int(x + width + padding_x)), min(frame_height, int(y + height + padding_y))
    search = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return False, previous_box
    scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, confidence, _, location = cv2.minMaxLoc(scores)
    if confidence < 0.3:
        return False, previous_box
    return True, (left + location[0], top + location[1], width, height)


def extract_reference_foreground(image: np.ndarray) -> np.ndarray:
    """Create an alpha channel so the reference image's background is not pasted."""
    if image.shape[2] == 4:
        return image
    height, width = image.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    border = max(2, min(width, height) // 20)
    rectangle = (border, border, max(2, width - border * 2), max(2, height - border * 2))
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)
    cv2.grabCut(image, mask, rectangle, background_model, foreground_model, 5, cv2.GC_INIT_WITH_RECT)
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.45)
    return np.dstack((image, alpha))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "gemini_configured": bool(os.getenv("GEMINI_API_KEY"))}


@app.post("/api/process")
async def process_video(
    video: UploadFile = File(...),
    prompt: str = Form(...),
    reference_image: UploadFile | None = File(default=None),
    target_box: str | None = Form(default=None),
) -> dict:
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Please upload a video file.")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="An editing prompt is required.")

    job_id = uuid.uuid4().hex
    job_dir = MEDIA_DIR / job_id
    job_dir.mkdir()
    source_path = job_dir / (video.filename or "source.mp4")
    output_path = job_dir / "edited-video.mp4"
    with source_path.open("wb") as destination:
        shutil.copyfileobj(video.file, destination)

    reference_path = None
    if reference_image:
        reference_path = job_dir / (reference_image.filename or "reference.png")
        with reference_path.open("wb") as destination:
            shutil.copyfileobj(reference_image.file, destination)

    try:
        interpretation = understand_prompt(prompt)
        try:
            parsed_box = json.loads(target_box) if target_box else None
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=400, detail="Target selection data is invalid. Draw a box around the object again.") from error
        resolved_box = parsed_box or locate_target_with_gemini(source_path, interpretation["target"])
        render_video(source_path, output_path, reference_path, interpretation, resolved_box)
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="FFmpeg is not installed or not on PATH.")
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Video processing failed: {error}")

    return {
        "job_id": job_id,
        "status": "complete",
        "interpretation": interpretation,
        "target_box": resolved_box,
        "output_url": f"/media/{job_id}/edited-video.mp4",
    }
