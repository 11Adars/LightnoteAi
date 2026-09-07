import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [video, setVideo] = useState(null)
  const [reference, setReference] = useState(null)
  const [prompt, setPrompt] = useState('Replace the Coca-Cola bottle with Pepsi.')
  const [status, setStatus] = useState('idle')
  const [progress, setProgress] = useState(0)
  const [resultUrl, setResultUrl] = useState('')
  const [error, setError] = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [referenceUrl, setReferenceUrl] = useState('')
  const [targetBox, setTargetBox] = useState(null)
  const [selectionStart, setSelectionStart] = useState(null)
  const [selectionPreview, setSelectionPreview] = useState(null)
  const [selectionMode, setSelectionMode] = useState(true)
  const [videoDimensions, setVideoDimensions] = useState({ width: 16, height: 9 })

  useEffect(() => {
    if (!video) return undefined
    const url = URL.createObjectURL(video)
    setVideoUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [video])

  useEffect(() => {
    if (!reference) return undefined
    const url = URL.createObjectURL(reference)
    setReferenceUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [reference])

  const parsePrompt = () => {
    const lowerPrompt = prompt.toLowerCase()
    const isRemoval = lowerPrompt.includes('remove')
    const match = prompt.match(/replace (?:the )?(.+?) (?:with|by) (.+?)(?:\.|$)/i)
    return {
      operation: isRemoval ? 'Remove object' : match ? 'Replace object' : 'Understand instruction',
      target: isRemoval ? prompt.replace(/remove (?:the )?/i, '').replace(/[.]$/, '') : match?.[1] || 'Object in the video',
      replacement: isRemoval ? 'Background reconstruction' : match?.[2] || 'Reference image or generated replacement',
    }
  }

  const handleVideo = (event) => {
    const file = event.target.files?.[0]
    if (file) setVideo(file)
  }

  const handleReference = (event) => {
    const file = event.target.files?.[0]
    if (file) setReference(file)
  }

  const getSelectionPoint = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return { x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) }
  }

  const startSelection = (event) => {
    if (!selectionMode) return
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setSelectionStart(getSelectionPoint(event))
    setTargetBox(null)
    setSelectionPreview(null)
  }

  const updateSelection = (event) => {
    if (!selectionMode || !selectionStart) return
    const end = getSelectionPoint(event)
    setSelectionPreview({ x: Math.min(selectionStart.x, end.x), y: Math.min(selectionStart.y, end.y), width: Math.abs(selectionStart.x - end.x), height: Math.abs(selectionStart.y - end.y) })
  }

  const finishSelection = (event) => {
    if (!selectionMode || !selectionStart) return
    const end = getSelectionPoint(event)
    const box = { x: Math.min(selectionStart.x, end.x), y: Math.min(selectionStart.y, end.y), width: Math.abs(selectionStart.x - end.x), height: Math.abs(selectionStart.y - end.y) }
    if (box.width > 0.02 && box.height > 0.02) setTargetBox(box)
    setSelectionStart(null)
    setSelectionPreview(null)
  }

  const processVideo = async () => {
    if (!video || !prompt.trim()) return
    setStatus('processing')
    setProgress(8)
    setError('')
    setResultUrl('')

    const formData = new FormData()
    formData.append('video', video)
    formData.append('prompt', prompt)
    if (reference) formData.append('reference_image', reference)
    if (targetBox) formData.append('target_box', JSON.stringify([targetBox.x, targetBox.y, targetBox.width, targetBox.height]))

    try {
      const response = await fetch('http://localhost:8000/api/process', { method: 'POST', body: formData })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail || 'The processing service returned an error.')
      }
      const data = await response.json()
      setProgress(100)
      setResultUrl(`http://localhost:8000${data.output_url}`)
      setStatus('complete')
    } catch (requestError) {
      setError(`${requestError.message} Start the FastAPI server and try again.`)
      setStatus('error')
      setProgress(0)
    }
  }

  const analysis = parsePrompt()

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Lightnote home"><span className="brand-mark">L</span> lightnote<span>ai</span></a>
        <div className="header-status"><span className="status-dot" /> Local prototype <span className="divider" /> v0.1</div>
      </header>

      <section className="intro">
        <div>
          <p className="eyebrow">AI video studio / 01</p>
          <h1>Change what’s<br /><em>inside</em> the frame.</h1>
        </div>
        <p className="intro-copy">Describe an object-level edit in plain language. Lightnote understands the instruction, tracks the subject, and renders a new video.</p>
      </section>

      <section className="workspace">
        <div className="input-column">
          <div className="section-heading"><span>01</span><h2>Source material</h2></div>
          <label className={`dropzone ${video ? 'has-file' : ''}`}>
            <input type="file" accept="video/*" onChange={handleVideo} />
            {videoUrl ? <div className={`target-select ${selectionMode ? 'selecting' : 'previewing'}`} style={{ aspectRatio: `${videoDimensions.width} / ${videoDimensions.height}` }} onPointerDown={startSelection} onPointerMove={updateSelection} onPointerUp={finishSelection}><video src={videoUrl} controls onLoadedMetadata={(event) => setVideoDimensions({ width: event.currentTarget.videoWidth, height: event.currentTarget.videoHeight })} /><div className="target-toolbar"><button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => setSelectionMode(true)} className={selectionMode ? 'active' : ''}>Select object</button><button type="button" onPointerDown={(event) => event.stopPropagation()} onClick={() => setSelectionMode(false)} className={!selectionMode ? 'active' : ''}>Preview video</button></div><span className="target-hint">{selectionMode ? 'Click and drag around the object to replace' : 'Use the video controls to play and scrub'}</span>{(targetBox || selectionPreview) && <span className="target-box" style={{ left: `${(targetBox || selectionPreview).x * 100}%`, top: `${(targetBox || selectionPreview).y * 100}%`, width: `${(targetBox || selectionPreview).width * 100}%`, height: `${(targetBox || selectionPreview).height * 100}%` }} />}</div> : <><span className="upload-glyph">+</span><strong>Drop a video here</strong><small>MP4, MOV or WebM / up to 100 MB</small></>}
            {video && <span className="file-name">{video.name}</span>}
          </label>

          <label className={`reference-row ${reference ? 'has-file' : ''}`}>
            <input type="file" accept="image/*" onChange={handleReference} />
            <span className="reference-thumb">{referenceUrl ? <img src={referenceUrl} alt="Reference preview" /> : '+'}</span>
            <span><strong>{reference ? reference.name : 'Add a reference image'}</strong><small>{reference ? 'Reference loaded' : 'Optional / helps guide the replacement'}</small></span>
            <span className="browse">Browse</span>
          </label>

          <div className="section-heading prompt-heading"><span>02</span><h2>Creative direction</h2></div>
          <label className="prompt-box"><span>Instruction</span><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="e.g. Replace the red mug with a blue ceramic cup" /><small>Be specific about the object you want to change.</small></label>

          <div className="analysis-card">
            <div className="analysis-top"><span>Model interpretation</span><span className="ai-chip">Gemini + CV pipeline</span></div>
            <div className="analysis-grid"><div><small>Operation</small><strong>{analysis.operation}</strong></div><div><small>Target</small><strong>{analysis.target}</strong></div><div><small>Replacement</small><strong>{analysis.replacement}</strong></div></div>
            <p className="selection-status">{targetBox ? 'Target area selected. The tracker will follow it through the video.' : 'Draw a box around the target in the source preview. Gemini can locate it automatically when configured.'}</p>
          </div>

          <button className="process-button" onClick={processVideo} disabled={!video || !prompt.trim() || !targetBox || status === 'processing'}>{status === 'processing' ? 'Processing…' : targetBox ? 'Start processing' : 'Select the target in the video'}<span>→</span></button>
          {error && <p className="error-message">{error}</p>}
        </div>

        <div className="output-column">
          <div className="section-heading"><span>03</span><h2>Result</h2><span className="result-state">{status === 'complete' ? 'Ready' : status === 'processing' ? 'Rendering' : 'Waiting for input'}</span></div>
          <div className={`result-stage ${resultUrl ? 'has-result' : ''}`}>
            {resultUrl ? <video src={resultUrl} controls autoPlay loop /> : <div className="empty-result"><div className="frame-icon"><span /></div><strong>Your edited video<br />will appear here</strong><small>Upload a source and describe your edit to begin.</small></div>}
          </div>
          {status === 'processing' && <div className="progress-panel"><div className="progress-copy"><span>Rendering your edit</span><strong>{progress}%</strong></div><div className="progress-track"><span style={{ width: `${progress}%` }} /></div><small>Detecting subject · tracking motion · compositing replacement</small></div>}
          {status === 'complete' && <a className="download-button" href={resultUrl} download="lightnoteai-edited-video.mp4">Download edited video <span>↓</span></a>}
          <div className="pipeline"><span className="pipeline-label">Pipeline</span><span className={status !== 'idle' ? 'active' : ''}>Understand</span><i>→</i><span className={status === 'processing' || status === 'complete' ? 'active' : ''}>Track & mask</span><i>→</i><span className={status === 'complete' ? 'active' : ''}>Render</span></div>
        </div>
      </section>
      <footer><span>Built for the LightnoteAI technical assignment</span><span>FastAPI · FFmpeg · OpenCV · Gemini</span></footer>
    </main>
  )
}

export default App
