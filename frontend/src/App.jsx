import React, { useState, useEffect, useRef, useCallback } from 'react'
import ControlPanel from './components/ControlPanel'
import VideoPlayer from './components/VideoPlayer'
import EvaluationPanel from './components/EvaluationPanel'
import AdminPanel from './components/AdminPanel'
import { MaskProvider, useMask } from './contexts/MaskContext'
import { GoogleLogin, googleLogout } from '@react-oauth/google'

const initialEvaluations = {
  Q1: { result: null, frameRanges: [] },
  Q2: { result: null, frameRanges: [] },
  Q3: { result: null, frameRanges: [] },
  Q4: { result: null, frameRanges: [] },
  Q5: { result: null, frameRanges: [] }
}

// Simple Error Boundary
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '20px', color: 'red', backgroundColor: '#fff' }}>
          <h1>Something went wrong.</h1>
          <pre>{this.state.error?.toString()}</pre>
          <button onClick={() => { localStorage.clear(); location.reload(); }}>Clear Cache & Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
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
  const [videoPreparing, setVideoPreparing] = useState(false)
  const [maskSources, setMaskSources] = useState([])
  const [selectedMaskSource, setSelectedMaskSource] = useState('')
  const [pendingMaskSource, setPendingMaskSource] = useState('') // UI용 즉시 반영
  const [maskSourceLoading, setMaskSourceLoading] = useState(false)
  const [videoUrls, setVideoUrls] = useState({})
  const [mobileActiveTab, setMobileActiveTab] = useState('video') // 모바일 탭 상태
  const [isMobile, setIsMobile] = useState(false) // 모바일 감지
  const [showAdminPanel, setShowAdminPanel] = useState(false) // 관리자 패널
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('vmask_user')
      if (saved === 'undefined' || saved === 'null') return null;
      return saved ? JSON.parse(saved) : null
    } catch (err) {
      console.error("Failed to parse user from localStorage", err)
      return null
    }
  })

  const videoPlayerRef = useRef(null)
  const maskSourceDebounceRef = useRef(null)

  useEffect(() => {
    console.log("App mounted. User:", user?.email);
  }, []);

  useEffect(() => {
    if (user) {
      console.log("Rendering main UI for user:", user.email);
    }
  }, [user]);

  // Google Login Success Handler
  const handleLoginSuccess = async (credentialResponse) => {
    try {
      console.log("Login success, verifying with backend...");
      const res = await fetch('/api/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: credentialResponse.credential })
      })
      const data = await res.json()
      if (data.success && data.user) {
        console.log("Backend verification success:", data.user.email);
        setUser(data.user)
        localStorage.setItem('vmask_user', JSON.stringify(data.user))
      } else {
        console.error("Login failed on backend", data)
        alert("로그인 세션 확인에 실패했습니다. (Google 계정 확인 필요)")
      }
    } catch (err) {
      console.error("Error during authentication", err)
      alert("로그인 중 서버 통신 오류가 발생했습니다.")
    }
  }

  const handleLogout = () => {
    console.log("Logging out...");
    googleLogout()
    setUser(null)
    localStorage.removeItem('vmask_user')
  }

  // 현재 비디오의 평가 기록 가져오기 + 최신 평가 자동 로드
  const fetchEvaluationHistory = useCallback(async (videoName, maskSource) => {
    if (!videoName || !user) return
    try {
      let url = `/api/evaluations?video_name=${encodeURIComponent(videoName)}`
      if (maskSource) url += `&mask_source=${maskSource}`
      const response = await fetch(url)
      const data = await response.json()
      const filtered = (data.evaluations || []).filter(e =>
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
              if (loaded[row.id]) {
                loaded[row.id] = {
                  result: row.result === 'N/A' ? null : row.result,
                  frameRanges: row.frameRanges || []
                }
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
  }, [user])

  // 비디오 목록 갱신 (mask_source에 따른 평가 상태 반영)
  const fetchVideos = useCallback(async (maskSource) => {
    try {
      const url = maskSource
        ? `/api/videos?mask_source=${maskSource}`
        : '/api/videos'
      const res = await fetch(url)
      const data = await res.json()
      const videoList = data.videos || []
      setVideos(videoList)
      return videoList
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

  const getTaskName = (videoName) => {
    if (!videoName) return ''
    const parts = videoName.split('_')
    if (parts.length > 1 && /^\d+$/.test(parts[parts.length - 1])) {
      return parts.slice(0, -1).join('_')
    }
    return videoName
  }

  const handleVideoSelect = useCallback(async (videoName, videoList) => {
    const video = (videoList || videos || []).find(v => v.name === videoName)
    if (video) {
      // UI 즉시 업데이트
      setCurrentVideo(video)
      setViewingMosaic(false)
      setVideoPreparing(true)
      setCurrentFrame(0)
      setVideoMeta({ fps: 30, frameCount: 0 })

      // 1. S3 URL을 먼저 가져와서, S3 영상이면 prepare-video를 건너뜀
      let fetchedUrls = {}
      try {
        const urlParams = selectedMaskSource ? `?mask_source=${selectedMaskSource}` : ''
        const urlRes = await fetch(`/api/video-urls/${videoName}${urlParams}`)
        fetchedUrls = await urlRes.json()
        setVideoUrls(fetchedUrls)
        const task = getTaskName(videoName)
        const isDualViewTask = ['text', 'tattoo'].includes(task)
        if (fetchedUrls.mosaic || (selectedMaskSource === 'ogq' && !isDualViewTask)) {
          setViewingMosaic(true)
        }
      } catch (err) {
        console.error('Failed to fetch video URLs:', err)
        setVideoUrls({})
      }

      // 2. S3에서 source URL이 있으면 변환 불필요 → 바로 재생 가능
      const isS3Video = !!(fetchedUrls.source || fetchedUrls.mosaic)
      if (!isS3Video) {
        // 로컬 비디오만 prepare-video 호출 (FFmpeg 변환 필요 시)
        try {
          const res = await fetch('/api/prepare-video/' + videoName, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mask_source: selectedMaskSource })
          })
          const data = await res.json()

          if (data.status === 'processing') {
            let isCompleted = false
            let retries = 0
            const maxRetries = 120
            while (!isCompleted && retries < maxRetries) {
              await new Promise(r => setTimeout(r, 1500))
              const statusUrl = selectedMaskSource
                ? `/api/conversion-status/${videoName}?mask_source=${selectedMaskSource}`
                : `/api/conversion-status/${videoName}`
              const statusRes = await fetch(statusUrl)
              const statusData = await statusRes.json()
              if (statusData.status === 'completed') {
                isCompleted = true
              } else if (statusData.status === 'failed' || statusData.status === 'unknown') {
                isCompleted = true
              }
              retries++
            }
          }
        } catch (err) {
          console.error('Video prepare request failed:', err)
        }
      }

      setVideoPreparing(false)
    }
  }, [videos, selectedMaskSource])

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
          mask_source: selectedMaskSource,
          user: user
        })
      })

      const data = await response.json()
      if (data.success) {
        await fetchVideos(selectedMaskSource)
        await fetchEvaluationHistory(currentVideo.name, selectedMaskSource)

        if (user) {
          const updatedUser = { ...user, saved_count: (user.saved_count || 0) + 1 }
          setUser(updatedUser)
          localStorage.setItem('vmask_user', JSON.stringify(updatedUser))
        }

        const maskedVideos = videos.filter(v =>
          selectedMaskSource
            ? v.availableMasks?.includes(selectedMaskSource)
            : (v.availableMasks?.length || 0) > 0
        )
        const currentIndex = maskedVideos.findIndex(v => v.name === currentVideo?.name)
        if (currentIndex < maskedVideos.length - 1) {
          handleVideoSelect(maskedVideos[currentIndex + 1].name)
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
  }, [currentVideo, evaluations, selectedMaskSource, videos, fetchVideos, fetchEvaluationHistory, user, handleVideoSelect])

  const handleToggleMosaic = useCallback(async () => {
    if (viewingMosaic) {
      setViewingMosaic(false)
      return
    }
    if (!currentVideo) return
    try {
      const checkUrl = selectedMaskSource
        ? `/api/mosaic-check/${currentVideo.name}?mask_source=${selectedMaskSource}`
        : `/api/mosaic-check/${currentVideo.name}`
      const checkRes = await fetch(checkUrl)
      const checkData = await checkRes.json()

      if (checkData.exists) {
        setViewingMosaic(true)
      } else {
        setMosaicGenerating(true)
        const genUrl = selectedMaskSource
          ? `/api/generate-mosaic/${currentVideo.name}?mask_source=${selectedMaskSource}`
          : `/api/generate-mosaic/${currentVideo.name}`
        const genRes = await fetch(genUrl, { method: 'POST' })
        const genData = await genRes.json()

        if (genData.status === 'processing' || genData.success) {
          if (videoPlayerRef.current) {
            const success = await videoPlayerRef.current.prepareMosaic()
            if (success) setViewingMosaic(true)
          }
        } else {
          alert('모자이크 생성 시작 실패: ' + (genData.error || 'Unknown error'))
        }
        setMosaicGenerating(false)
      }
    } catch (err) {
      setMosaicGenerating(false)
      console.error('Mosaic toggle error:', err)
      alert('모자이크 처리 중 오류가 발생했습니다.')
    }
  }, [viewingMosaic, currentVideo, selectedMaskSource])

  const handleMetadataLoaded = useCallback((meta) => {
    setVideoMeta(meta)
  }, [])

  const handleTimeUpdate = useCallback((time) => {
    // videoMeta가 아직 로드되지 않았을 경우를 대비한 방어 로직
    const fps = videoMeta.fps || 30
    const frameCount = videoMeta.frameCount
    let frame = Math.floor(time * fps + 0.001) 
    
    // frameCount가 0보다 클 때만 캡핑 (마지막 프레임 초과 방지)
    if (frameCount > 0 && frame >= frameCount) {
      frame = frameCount - 1
    }
    
    setCurrentFrame(Math.max(0, frame))
  }, [videoMeta])

  // mask source 변경 시 overlay 상태 초기화 (디바운스 적용)
  const handleMaskSourceChange = (source) => {
    // 이전 디바운스 타이머 취소
    if (maskSourceDebounceRef.current) {
      clearTimeout(maskSourceDebounceRef.current)
    }

    // UI는 즉시 업데이트 (선택된 항목 표시)
    setPendingMaskSource(source)

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

  // ===== useEffect hooks =====

  // 모바일 감지
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth <= 768)
    }
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  // 초기 로드: mask sources를 로드
  useEffect(() => {
    fetchMaskSources()
  }, [fetchMaskSources])

  // 비디오 변경 또는 mask_source 변경 시 평가 기록 로드 + 최신 평가 자동 불러오기
  useEffect(() => {
    if (currentVideo?.name) {
      fetchEvaluationHistory(currentVideo.name, selectedMaskSource)
    }
  }, [currentVideo?.name, selectedMaskSource, fetchEvaluationHistory])

  // mask_source 변경 시 비디오 목록도 갱신 (평가 상태 반영) + S3 URL 갱신
  useEffect(() => {
    if (selectedMaskSource) {
      fetchVideos(selectedMaskSource)
      // mask source 변경 시 현재 비디오의 S3 URL도 갱신
      if (currentVideo?.name) {
        fetch(`/api/video-urls/${currentVideo.name}?mask_source=${selectedMaskSource}`)
          .then(res => res.json())
          .then(data => {
            setVideoUrls(data)
            const task = getTaskName(currentVideo.name)
            const isDualViewTask = ['text', 'tattoo'].includes(task)
            if (data.mosaic || (selectedMaskSource === 'ogq' && !isDualViewTask)) {
              setViewingMosaic(true)
            } else {
              setViewingMosaic(false)
            }
          })
          .catch(() => setVideoUrls({}))
      }
    }
  }, [selectedMaskSource, fetchVideos, currentVideo?.name])

  // mask sources 로드 후 첫 번째를 기본값으로 설정하고 비디오 목록 로드
  useEffect(() => {
    if (maskSources.length > 0 && !selectedMaskSource) {
      const firstSource = maskSources[0].name
      setSelectedMaskSource(firstSource)
      setPendingMaskSource(firstSource)
      fetchVideos(firstSource).then(vids => {
        if (vids && vids.length > 0) {
          handleVideoSelect(vids[0].name, vids)
        }
      })
    }
  }, [maskSources, selectedMaskSource, fetchVideos, handleVideoSelect])

  // 키보드 단축키
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
        e.preventDefault()
        if (currentVideo && !isSaving) {
          handleSave()
        }
        return
      }

      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return

      if (e.code === 'Tab') {
        e.preventDefault()
        toggleMask()
      }

      if (e.code === 'KeyM') {
        e.preventDefault()
        if (currentVideo) {
          handleToggleMosaic()
        }
      }

      if (e.code === 'Space') {
        e.preventDefault()
        videoPlayerRef.current?.togglePlay()
      }

      if (e.code === 'ArrowLeft' || e.code === 'ArrowRight') {
        e.preventDefault()
        const direction = e.code === 'ArrowLeft' ? -1 : 1
        const frames = e.shiftKey ? 30 : 1
        videoPlayerRef.current?.seekFrames(direction * frames)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [currentVideo, isSaving, handleSave, toggleMask, handleToggleMosaic])



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
        frameRanges: [...(prev[questionId]?.frameRanges || []), { start: frame, end: frame }]
      }
    }))
  }

  // 프레임 범위의 시작/끝 수정
  const handleUpdateFrameRange = (questionId, rangeIndex, field, value) => {
    setEvaluations(prev => {
      if (!prev[questionId]) return prev;
      const newRanges = [...(prev[questionId].frameRanges || [])]
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
        frameRanges: (prev[questionId]?.frameRanges || []).filter((_, i) => i !== rangeIndex)
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
          if (loaded[row.id]) {
            loaded[row.id] = {
              result: row.result === 'N/A' ? null : row.result,
              frameRanges: row.frameRanges || []
            }
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
    <div className="app-container" style={{ position: 'relative', width: '100%', height: '100%' }}>
      {!user ? (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          backgroundColor: '#fff', fontFamily: 'sans-serif', zIndex: 9999
        }}>
          <h1 style={{ marginBottom: '10px', fontSize: '26px', fontWeight: '600' }}>로그인 또는 회원 가입</h1>
          <p style={{ color: '#666', marginBottom: '40px', fontSize: '15px' }}>더 스마트한 응답, 파일 및 이미지 로드 등을 보관할 수 있습니다.</p>
          
          <div style={{ width: '320px', display: 'flex', justifyContent: 'center' }}>
            <GoogleLogin
              onSuccess={handleLoginSuccess}
              onError={() => console.log('Login Failed')}
              theme="outline"
              shape="pill"
              width="320px"
              locale="ko"
            />
          </div>
        </div>
      ) : (
        <div style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row'
        }}>
          {/* 모바일: 선택된 탭만 표시 / 데스크톱: 모두 표시 */}
          {(!isMobile || mobileActiveTab === 'control') && (
            <ControlPanel
              user={user}
              onLogout={handleLogout}
              onOpenAdmin={() => setShowAdminPanel(true)}
              videos={videos || []}
              currentVideo={currentVideo}
              currentFrame={currentFrame}
              frameCount={videoMeta.frameCount}
              fps={videoMeta.fps}
              viewingMosaic={viewingMosaic}
              mosaicGenerating={mosaicGenerating}
              maskSources={maskSources || []}
              selectedMaskSource={pendingMaskSource || selectedMaskSource}
              maskSourceLoading={maskSourceLoading}
              onMaskSourceChange={handleMaskSourceChange}
              onVideoSelect={handleVideoSelect}
              onPrevVideo={handlePrevVideo}
              onNextVideo={handleNextVideo}
              onSeekFrames={handleSeekFrames}
              onToggleMosaic={handleToggleMosaic}
            />
          )}

          {(!isMobile || mobileActiveTab === 'video') && (
            <VideoPlayer
              ref={videoPlayerRef}
              currentVideo={currentVideo}
              viewingMosaic={viewingMosaic}
              videoPreparing={videoPreparing}
              selectedMaskSource={selectedMaskSource}
              videoUrls={videoUrls}
              onMetadataLoaded={handleMetadataLoaded}
              onTimeUpdate={handleTimeUpdate}
              onMaskLoaded={handleMaskLoaded}
              evaluationHistory={evaluationHistory}
              onLoadEvaluation={handleLoadEvaluation}
              onSeekToFrame={handleSeekToFrame}
            />
          )}

          {(!isMobile || mobileActiveTab === 'evaluate') && (
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
          )}

          {/* 모바일 하단 탭 네비게이션 */}
          {isMobile && (
            <nav className="mobile-tab-nav">
              <button
                className={`mobile-tab-btn ${mobileActiveTab === 'control' ? 'active' : ''}`}
                onClick={() => setMobileActiveTab('control')}
              >
                <span className="mobile-tab-icon">⚙️</span>
                <span>설정</span>
              </button>
              <button
                className={`mobile-tab-btn ${mobileActiveTab === 'video' ? 'active' : ''}`}
                onClick={() => setMobileActiveTab('video')}
              >
                <span className="mobile-tab-icon">▶️</span>
                <span>비디오</span>
              </button>
              <button
                className={`mobile-tab-btn ${mobileActiveTab === 'evaluate' ? 'active' : ''}`}
                onClick={() => setMobileActiveTab('evaluate')}
              >
                <span className="mobile-tab-icon">✅</span>
                <span>평가</span>
              </button>
            </nav>
          )}
        </div>
      )}

      {showAdminPanel && (
        <AdminPanel
          user={user}
          onClose={() => setShowAdminPanel(false)}
        />
      )}
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <MaskProvider>
        <AppContent />
      </MaskProvider>
    </ErrorBoundary>
  )
}
