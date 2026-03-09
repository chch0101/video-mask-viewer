import { useState, useEffect, useRef, useCallback } from 'react'
import ControlPanel from './components/ControlPanel'
import VideoPlayer from './components/VideoPlayer'
import EvaluationPanel from './components/EvaluationPanel'
import { MaskProvider, useMask } from './contexts/MaskContext'

const initialEvaluations = {
  Q1: { result: null, frameRanges: [] },
  Q2: { result: null, frameRanges: [] },
  Q3: { result: null, frameRanges: [] },
  Q4: { result: null, frameRanges: [] },
  Q5: { result: null, frameRanges: [] }
}

function AppContent() {
  const { toggleMask } = useMask()

  const [videos, setVideos] = useState([])
  const [currentVideo, setCurrentVideo] = useState(null)
  const [videoMeta, setVideoMeta] = useState({ frameCount: 0, fps: 30 })
  const [currentFrame, setCurrentFrame] = useState(0)
  const [evaluations, setEvaluations] = useState(initialEvaluations)
  const [isSaving, setIsSaving] = useState(false)
  const [evaluationHistory, setEvaluationHistory] = useState([])
  const [viewingMosaic, setViewingMosaic] = useState(false)
  const [mosaicGenerating, setMosaicGenerating] = useState(false)
  const [viewingOverlay, setViewingOverlay] = useState(false)
  const [overlayGenerating, setOverlayGenerating] = useState(false)
  const [videoPreparing, setVideoPreparing] = useState(false)
  const [maskSources, setMaskSources] = useState([])
  const [selectedMaskSource, setSelectedMaskSource] = useState('')
  const [pendingMaskSource, setPendingMaskSource] = useState('') // UI용 즉시 반영
  const [maskSourceLoading, setMaskSourceLoading] = useState(false)

  const videoPlayerRef = useRef(null)
  const maskSourceDebounceRef = useRef(null)

  // 현재 비디오의 평가 기록 가져오기 + 최신 평가 자동 로드
  const fetchEvaluationHistory = useCallback(async (videoName, maskSource) => {
    if (!videoName) return
    try {
      const url = maskSource
        ? `/api/evaluations?mask_source=${maskSource}`
        : '/api/evaluations'
      const response = await fetch(url)
      const data = await response.json()
      const filtered = data.evaluations.filter(e =>
        e.filename.includes(videoName)
      )
      setEvaluationHistory(filtered)

      // 기존 평가가 있으면 가장 최신 평가를 자동으로 불러오기
      if (filtered.length > 0) {
        const latestFilename = filtered[0].filename // 이미 역순 정렬됨
        try {
          const evalRes = await fetch(`/api/evaluations/${latestFilename}`)
          const evalData = await evalRes.json()
          if (evalData.results) {
            const loaded = { ...initialEvaluations }
            evalData.results.forEach(row => {
              loaded[row.id] = {
                result: row.result === 'N/A' ? null : row.result,
                frameRanges: row.frameRanges || []
              }
            })
            setEvaluations(loaded)
          }
        } catch (err) {
          console.error('Failed to auto-load evaluation:', err)
        }
      } else {
        // 기존 평가가 없으면 초기화
        setEvaluations(initialEvaluations)
      }
    } catch (err) {
      console.error('Failed to load evaluation history:', err)
    }
  }, [])

  // 비디오 목록 갱신 (mask_source에 따른 평가 상태 반영)
  const fetchVideos = useCallback(async (maskSource) => {
    try {
      const url = maskSource
        ? `/api/videos?mask_source=${maskSource}`
        : '/api/videos'
      const res = await fetch(url)
      const data = await res.json()
      setVideos(data.videos)
      return data.videos
    } catch (err) {
      console.error('Failed to load videos:', err)
      return []
    }
  }, [])

  // masks 폴더 목록 조회
  const fetchMaskSources = useCallback(async () => {
    try {
      const res = await fetch('/api/mask-sources')
      const data = await res.json()
      setMaskSources(data.sources || [])
    } catch (err) {
      console.error('Failed to load mask sources:', err)
    }
  }, [])

  // 초기 로드: mask sources를 먼저 로드하고, 첫 번째 mask source로 비디오 목록 로드
  useEffect(() => {
    const init = async () => {
      // 1. mask sources 로드
      await fetchMaskSources()
    }
    init()
  }, [])

  // mask sources 로드 후 첫 번째를 기본값으로 설정하고 비디오 목록 로드
  useEffect(() => {
    if (maskSources.length > 0 && !selectedMaskSource) {
      const firstSource = maskSources[0].name
      setSelectedMaskSource(firstSource)
      setPendingMaskSource(firstSource)
      // 첫 번째 mask source로 비디오 목록 로드
      fetchVideos(firstSource).then(vids => {
        if (vids.length > 0) {
          handleVideoSelect(vids[0].name)
        }
      })
    }
  }, [maskSources])

  // 컴포넌트 언마운트 시 디바운스 타이머 정리
  useEffect(() => {
    return () => {
      if (maskSourceDebounceRef.current) {
        clearTimeout(maskSourceDebounceRef.current)
      }
    }
  }, [])

  // mask source 변경 시 overlay 상태 초기화 (디바운스 적용)
  const handleMaskSourceChange = (source) => {
    // 이전 디바운스 타이머 취소
    if (maskSourceDebounceRef.current) {
      clearTimeout(maskSourceDebounceRef.current)
    }

    // UI는 즉시 업데이트 (선택된 항목 표시)
    setPendingMaskSource(source)

    // overlay 모드는 즉시 해제
    if (viewingOverlay) {
      setViewingOverlay(false)
    }

    // 실제 비디오 로드는 디바운스 (300ms)
    // 빠르게 여러 번 변경 시 마지막 선택만 로드됨
    maskSourceDebounceRef.current = setTimeout(() => {
      setSelectedMaskSource(source)
      setMaskSourceLoading(true)
      maskSourceDebounceRef.current = null
    }, 300)
  }

  // mask 로드 완료 콜백
  const handleMaskLoaded = () => {
    setMaskSourceLoading(false)
  }

  // 비디오 변경 또는 mask_source 변경 시 평가 기록 로드 + 최신 평가 자동 불러오기
  useEffect(() => {
    if (currentVideo?.name) {
      fetchEvaluationHistory(currentVideo.name, selectedMaskSource)
    }
  }, [currentVideo?.name, selectedMaskSource, fetchEvaluationHistory])

  // mask_source 변경 시 비디오 목록도 갱신 (평가 상태 반영)
  useEffect(() => {
    if (selectedMaskSource) {
      fetchVideos(selectedMaskSource)
    }
  }, [selectedMaskSource, fetchVideos])

  const handleSave = useCallback(async () => {
    if (!currentVideo) return

    setIsSaving(true)
    try {
      const response = await fetch('/api/evaluations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_name: currentVideo.name,
          evaluations: evaluations,
          mask_source: selectedMaskSource
        })
      })

      const data = await response.json()
      if (data.success) {
        // 비디오 목록 갱신 (평가 완료 상태 반영)
        await fetchVideos(selectedMaskSource)
        await fetchEvaluationHistory(currentVideo.name, selectedMaskSource)

        // 자동으로 다음 비디오로 이동
        const currentIndex = videos.findIndex(v => v.name === currentVideo?.name)
        if (currentIndex < videos.length - 1) {
          handleVideoSelect(videos[currentIndex + 1].name)
        } else {
          alert('모든 비디오의 평가가 완료되었습니다! 🎉')
        }
      } else {
        alert('저장 실패: ' + (data.error || 'Unknown error'))
      }
    } catch (err) {
      console.error('Save error:', err)
      alert('저장 중 오류가 발생했습니다.')
    } finally {
      setIsSaving(false)
    }
  }, [currentVideo, evaluations, selectedMaskSource, videos, fetchVideos, fetchEvaluationHistory])

  // 키보드 단축키
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+S / Cmd+S: CSV 저장 (어디서든 동작)
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
        e.preventDefault()
        if (currentVideo && !isSaving) {
          handleSave()
        }
        return
      }

      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return

      // Tab: 마스크 on/off 토글
      if (e.code === 'Tab') {
        e.preventDefault()
        toggleMask()
      }

      // Space: 영상 재생/멈춤
      if (e.code === 'Space') {
        e.preventDefault()
        videoPlayerRef.current?.togglePlay()
      }

      // 좌우 화살표 - Shift+화살표: 30프레임, 화살표만: 1프레임
      if (e.code === 'ArrowLeft' || e.code === 'ArrowRight') {
        e.preventDefault()
        const direction = e.code === 'ArrowLeft' ? -1 : 1
        const frames = e.shiftKey ? 30 : 1
        videoPlayerRef.current?.seekFrames(direction * frames)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [currentVideo, isSaving, handleSave, toggleMask])

  const handleVideoSelect = async (videoName) => {
    const video = videos.find(v => v.name === videoName)
    if (video) {
      setViewingMosaic(false)
      setViewingOverlay(false)
      setVideoPreparing(true)

      try {
        // 비디오 변환이 필요하면 미리 수행
        const res = await fetch(`/api/prepare-video/${videoName}`, { method: 'POST' })
        const data = await res.json()
        if (data.converted?.length > 0) {
          console.log(`Video prepared: ${data.message}`)
        }
      } catch (err) {
        console.error('Video prepare failed:', err)
      }

      setVideoPreparing(false)
      setCurrentVideo(video)
    }
  }

  const handlePrevVideo = () => {
    const currentIndex = videos.findIndex(v => v.name === currentVideo?.name)
    if (currentIndex > 0) {
      handleVideoSelect(videos[currentIndex - 1].name)
    }
  }

  const handleNextVideo = () => {
    const currentIndex = videos.findIndex(v => v.name === currentVideo?.name)
    if (currentIndex < videos.length - 1) {
      handleVideoSelect(videos[currentIndex + 1].name)
    }
  }

  const handleSeekFrames = (frames) => {
    videoPlayerRef.current?.seekFrames(frames)
  }

  // 모자이크 보기 토글
  const handleToggleMosaic = async () => {
    if (viewingMosaic) {
      // 모자이크 모드 OFF → 원래 source+mask 뷰로 복귀
      setViewingMosaic(false)
      return
    }

    if (!currentVideo) return

    try {
      // 모자이크 영상 존재 여부 확인 (mask_source 파라미터 포함)
      const checkUrl = selectedMaskSource
        ? `/api/mosaic-check/${currentVideo.name}?mask_source=${selectedMaskSource}`
        : `/api/mosaic-check/${currentVideo.name}`
      const checkRes = await fetch(checkUrl)
      const checkData = await checkRes.json()

      if (checkData.exists) {
        // 이미 존재하면 바로 모자이크 모드 ON
        setViewingMosaic(true)
      } else {
        // 없으면 생성
        setMosaicGenerating(true)
        const genRes = await fetch('/api/mosaic-generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            video_name: currentVideo.name,
            mask_source: selectedMaskSource
          })
        })
        const genData = await genRes.json()
        setMosaicGenerating(false)

        if (genData.success) {
          setViewingMosaic(true)
        } else {
          alert('모자이크 생성 실패: ' + (genData.error || 'Unknown error'))
        }
      }
    } catch (err) {
      setMosaicGenerating(false)
      console.error('Mosaic toggle error:', err)
      alert('모자이크 처리 중 오류가 발생했습니다.')
    }
  }

  // 오버레이 보기 토글
  const handleToggleOverlay = async () => {
    if (viewingOverlay) {
      // 오버레이 모드 OFF → 원래 source+mask 뷰로 복귀
      setViewingOverlay(false)
      return
    }

    if (!currentVideo) return

    try {
      // 오버레이 영상 존재 여부 확인 (mask_source 파라미터 포함)
      const checkUrl = selectedMaskSource
        ? `/api/overlay-check/${currentVideo.name}?mask_source=${selectedMaskSource}`
        : `/api/overlay-check/${currentVideo.name}`
      const checkRes = await fetch(checkUrl)
      const checkData = await checkRes.json()

      if (checkData.exists) {
        // 이미 존재하면 바로 오버레이 모드 ON
        setViewingOverlay(true)
      } else {
        // 없으면 생성
        setOverlayGenerating(true)
        const genRes = await fetch('/api/overlay-generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            video_name: currentVideo.name,
            opacity: 0.5,
            mask_source: selectedMaskSource
          })
        })
        const genData = await genRes.json()
        setOverlayGenerating(false)

        if (genData.success) {
          setViewingOverlay(true)
        } else {
          alert('오버레이 생성 실패: ' + (genData.error || 'Unknown error'))
        }
      }
    } catch (err) {
      setOverlayGenerating(false)
      console.error('Overlay toggle error:', err)
      alert('오버레이 처리 중 오류가 발생했습니다.')
    }
  }

  const handleMetadataLoaded = (meta) => {
    setVideoMeta(meta)
  }

  const handleTimeUpdate = (time) => {
    setCurrentFrame(Math.floor(time * videoMeta.fps))
  }

  // 평가 결과 설정 (O/X 클릭 시 프레임 기록 유지)
  const handleEvaluate = (questionId, result) => {
    setEvaluations(prev => ({
      ...prev,
      [questionId]: { ...prev[questionId], result }
    }))
  }

  // 새로운 프레임 범위 추가
  const handleAddFrameRange = (questionId) => {
    const frame = getCurrentFrame()
    setEvaluations(prev => ({
      ...prev,
      [questionId]: {
        ...prev[questionId],
        frameRanges: [...prev[questionId].frameRanges, { start: frame, end: frame }]
      }
    }))
  }

  // 프레임 범위의 시작/끝 수정
  const handleUpdateFrameRange = (questionId, rangeIndex, field, value) => {
    setEvaluations(prev => {
      const newRanges = [...prev[questionId].frameRanges]
      newRanges[rangeIndex] = { ...newRanges[rangeIndex], [field]: value }
      return {
        ...prev,
        [questionId]: { ...prev[questionId], frameRanges: newRanges }
      }
    })
  }

  // 프레임 범위 삭제
  const handleRemoveFrameRange = (questionId, rangeIndex) => {
    setEvaluations(prev => ({
      ...prev,
      [questionId]: {
        ...prev[questionId],
        frameRanges: prev[questionId].frameRanges.filter((_, i) => i !== rangeIndex)
      }
    }))
  }

  const getCurrentFrame = () => {
    return videoPlayerRef.current?.getCurrentFrame() || 0
  }


  // 기존 평가 불러오기
  const handleLoadEvaluation = async (filename) => {
    try {
      const response = await fetch(`/api/evaluations/${filename}`)
      const data = await response.json()
      if (data.results) {
        const loaded = { ...initialEvaluations }
        data.results.forEach(row => {
          loaded[row.id] = {
            result: row.result === 'N/A' ? null : row.result,
            frameRanges: row.frameRanges || []
          }
        })
        setEvaluations(loaded)
      }
    } catch (err) {
      console.error('Failed to load evaluation:', err)
    }
  }

  // 특정 프레임으로 이동
  const handleSeekToFrame = (frame) => {
    if (frame !== null && frame !== undefined && videoPlayerRef.current) {
      const fps = videoMeta.fps || 30
      const targetTime = frame / fps
      videoPlayerRef.current.seekToTime(targetTime)
    }
  }

  return (
    <div className="app-container">
      <ControlPanel
        videos={videos}
        currentVideo={currentVideo}
        currentFrame={currentFrame}
        frameCount={videoMeta.frameCount}
        fps={videoMeta.fps}
        viewingMosaic={viewingMosaic}
        mosaicGenerating={mosaicGenerating}
        viewingOverlay={viewingOverlay}
        overlayGenerating={overlayGenerating}
        maskSources={maskSources}
        selectedMaskSource={pendingMaskSource || selectedMaskSource}
        maskSourceLoading={maskSourceLoading}
        onMaskSourceChange={handleMaskSourceChange}
        onVideoSelect={handleVideoSelect}
        onPrevVideo={handlePrevVideo}
        onNextVideo={handleNextVideo}
        onSeekFrames={handleSeekFrames}
        onToggleMosaic={handleToggleMosaic}
        onToggleOverlay={handleToggleOverlay}
      />

      <VideoPlayer
        ref={videoPlayerRef}
        currentVideo={currentVideo}
        viewingMosaic={viewingMosaic}
        viewingOverlay={viewingOverlay}
        videoPreparing={videoPreparing}
        selectedMaskSource={selectedMaskSource}
        onMetadataLoaded={handleMetadataLoaded}
        onTimeUpdate={handleTimeUpdate}
        onMaskLoaded={handleMaskLoaded}
        evaluationHistory={evaluationHistory}
        onLoadEvaluation={handleLoadEvaluation}
        onSeekToFrame={handleSeekToFrame}
      />

      <EvaluationPanel
        evaluations={evaluations}
        onEvaluate={handleEvaluate}
        onAddFrameRange={handleAddFrameRange}
        onUpdateFrameRange={handleUpdateFrameRange}
        onRemoveFrameRange={handleRemoveFrameRange}
        onSave={handleSave}
        getCurrentFrame={getCurrentFrame}
        currentVideoName={currentVideo?.name}
        isSaving={isSaving}
      />
    </div>
  )
}

export default function App() {
  return (
    <MaskProvider>
      <AppContent />
    </MaskProvider>
  )
}
