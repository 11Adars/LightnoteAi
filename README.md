# LightnoteAI

LightnoteAI is a full-stack prototype for editing an object in a video using a natural-language instruction.

Example: upload a video of a person holding a Coca-Cola bottle, upload a Pepsi reference image, select the bottle, and enter `Replace the Coca-Cola bottle with Pepsi.`

## Features

- Video upload with local preview and playback controls
- Optional reference-image upload
- Natural-language editing prompt
- First-frame target selection by drawing a box around the object
- Gemini prompt interpretation when an API key is configured
- OpenCV target tracking through the video
- ROI inpainting to reduce the visibility of the original object
- Foreground extraction from the reference image
- FFmpeg output encoding with original audio preserved
- Output preview and download

## Architecture

```text
React + Vite frontend
        |
        | multipart upload: video, prompt, reference image, target box
        v
FastAPI backend
        |
        +-- Gemini 2.5 Flash: prompt interpretation and optional target localization
        +-- OpenCV: target tracking, template fallback, foreground extraction, inpainting
        +-- FFmpeg: video/audio encoding and output delivery
```

The frontend is responsible for the user workflow and preview only. The backend owns prompt interpretation and video processing.

## AI and video approach

Gemini 2.5 Flash is used when `GEMINI_API_KEY` is available. It converts the prompt into structured data:

```json
{
  "operation": "replace_object",
  "target": "Coca-Cola bottle",
  "replacement": "Pepsi"
}
```

The user-selected target box is the reliable source of pixel coordinates. Gemini can also attempt first-frame localization, but the manual box remains available because natural language alone does not reliably identify exact pixels in every video.

OpenCV tracks the target region frame by frame. The backend repairs the selected region with ROI inpainting, extracts the foreground from the reference image, composites it into the moving region, and uses FFmpeg to restore the original audio.

## Requirements

Install these before running the project:

- Windows, macOS, or Linux
- Node.js 18 or newer
- Python 3.11 or newer
- FFmpeg available on PATH
- Optional Gemini API key

On Windows, FFmpeg can be installed with:

```powershell
winget install Gyan.FFmpeg.Shared
```

Verify it with:

```powershell
ffmpeg -version
```

## Complete local setup

Clone the repository and enter the project folder:

```powershell
git clone https://github.com/YOUR_USERNAME/lightnoteai.git
cd lightnoteai
```

### Terminal 1: backend

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once in PowerShell as your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Install backend dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

Optional Gemini setup:

```powershell
Copy-Item .env.example .env
```

Open `.env` and add your key:

```text
GEMINI_API_KEY=your_key_here
```

Start the API:

```powershell
python -m uvicorn backend.main:app --reload --port 8000
```

Keep this terminal running.

### Terminal 2: frontend

Open a second terminal in the project folder:

```powershell
npm install
npm run dev
```

Open the URL printed by Vite, normally:

```text
http://127.0.0.1:5173
```

### Use the application

1. Upload a source video.
2. Upload a clean reference image, such as a Pepsi bottle.
3. Choose **Select object**.
4. Click and drag a rectangle tightly around the object in the video preview.
5. Enter an instruction such as `Replace the Coca-Cola bottle with Pepsi.`
6. Click **Start processing**.
7. Wait for the rendered result, then preview or download it.

For the best result, the reference image should contain the product clearly and the selected box should include only the target object, with minimal surrounding background.

## API

Health check:

```text
GET http://127.0.0.1:8000/api/health
```

Processing endpoint:

```text
POST http://127.0.0.1:8000/api/process
```

Multipart fields:

- `video`: source video file
- `prompt`: natural-language instruction
- `reference_image`: optional image file
- `target_box`: optional JSON array `[x, y, width, height]` using normalized values from `0` to `1`


## Why this approach

This approach keeps the frontend simple and puts processing behind a backend API. It uses proven tools instead of training a model from scratch, supports a working local demo without a mandatory paid API key, and makes the object-selection step visible and explainable during an interview.

## Known limitations

- The current object mask starts from a rectangular user-selected box, so some surrounding pixels may remain.
- OpenCV tracking can lose the object during severe occlusion, fast motion, or large scale changes.
- CPU processing is sequential and can take longer than the source video duration.
- The current prototype is not production-quality generative video replacement. A stronger production pipeline would use Grounding DINO or YOLO for detection, SAM for segmentation, optical-flow or point tracking, GPU inpainting, asynchronous jobs, and progress events.
- Gemini is optional. Without it, the local prompt parser handles common `replace ... with ...` and `remove ...` instructions.
