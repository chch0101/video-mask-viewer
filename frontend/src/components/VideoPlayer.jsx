import { useRef, useEffect, useImperativeHandle, forwardRef, useState, useCallback } from 'react'
import { useMask } from '../contexts/MaskContext'

const PLAYBACK_RATES = [0.25, 0.5, 1, 1.5, 2]

// CSS blendMode → Canvas globalCompositeOperation 매핑
const BLEND_MAP = {
  normal: 'source-over',
  multiply: 'multiply',
  screen: 'screen',
  overlay: 'overlay',
  difference: 'difference'
}

const VideoPlayer = forwardRef(function VideoPlayer({
  currentVideo,
  viewingMosaic,
  viewingOverlay,
  videoPreparing = false,
  selectedMaskSource = '',
  videoUrls = {},
  onMetadataLoaded,
  onTimeUpdate,
  onMaskLoaded,
  evaluationHistory = [],
  onLoadEvaluation,
  onSeekToFrame
}, ref) {
  const { maskSettings } = useMask()
  const sourceVideoRef = useRef(null)
  const maskVideoRef = useRef(null)
  const mosaicVideoRef = useRef(null)
  const overlayVideoRef = useRef(null)
  const canvasRef = useRef(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [debugInfo, setDebugInfo] = useState('Loading...')
  const [selectedEvaluation, setSelectedEvaluation] = useState(null)
  const [evaluationDetails, setEvaluationDetails] = useState(null)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [maskConverting, setMaskConverting] = useState(false)
  const [sourceConverting, setSourceConverting] = useState(false)
  const [retryCount, setRetryCount] = useState(0)
  const maskLoadTimerRef = useRef(null)
  const maskLoadedRef = useRef(false)
  const sourceLoadTimerRef = useRef(null)
  const sourceLoadedRef = useRef(false)
  const fpsRef = useRef(30)
  const maskFpsRef = useRef(30)
  // source와 mask의 duration 비율 (다른 길이일 때 동기화용)
  const durationRatioRef = useRef(1)
  const renderAnimRef = useRef(null)
  const drawFrameRef = useRef(null)
  // 실시간 FPS 추적
  const [liveFps, setLiveFps] = useState({ source: 0, mask: 0 })
  // 마지막 seek 시간 추적 (seek 빈도 제한용)
  const lastSyncSeekRef = useRef(0)
  // playbackRate를 ref로도 관리 (동기화 루프에서 최신 값 참조용)
  const playbackRateRef = useRef(1)
  // 모자이크 전환 시 현재 시간 저장
  const savedTimeRef = useRef(0)
  // 비디오 로드 재시도 타이머
  const retryTimerRef = useRef(null)
  const retryCountRef = useRef(0)

  // Canvas에 현재 프레임을 그리는 함수
  const drawFrame = useCallback(() => {
    const canvas = canvasRef.current
    const sourceVideo = sourceVideoRef.current
    const maskVideo = maskVideoRef.current
    const mosaicVideo = mosaicVideoRef.current
    const overlayVideo = overlayVideoRef.current

    // 오버레이 모드일 때 (미리 합성된 영상)
    if (viewingOverlay && overlayVideo && overlayVideo.readyState >= 2) {
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (canvas.width !== overlayVideo.videoWidth || canvas.height !== overlayVideo.videoHeight) {
        canvas.width = overlayVideo.videoWidth
        canvas.height = overlayVideo.videoHeight
      }
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.drawImage(overlayVideo, 0, 0, canvas.width, canvas.height)
      return
    }

    // 모자이크 모드일 때
    if (viewingMosaic && mosaicVideo && mosaicVideo.readyState >= 2) {
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (canvas.width !== mosaicVideo.videoWidth || canvas.height !== mosaicVideo.videoHeight) {
        canvas.width = mosaicVideo.videoWidth
        canvas.height = mosaicVideo.videoHeight
      }
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
      ctx.drawImage(mosaicVideo, 0, 0, canvas.width, canvas.height)
      return
    }

    // 기존 source+mask 합성 모드
    if (!canvas || !sourceVideo || sourceVideo.readyState < 2) return

    const ctx = canvas.getContext('2d')

    // Canvas 크기를 비디오에 맞춤 (최초 또는 리사이즈 시)
    if (canvas.width !== sourceVideo.videoWidth || canvas.height !== sourceVideo.videoHeight) {
      canvas.width = sourceVideo.videoWidth
      canvas.height = sourceVideo.videoHeight
    }

    // 1. 소스 비디오 그리기
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
    ctx.drawImage(sourceVideo, 0, 0, canvas.width, canvas.height)

    // 2. 마스크 비디오 합성 (visible이고 마스크가 준비된 경우)
    if (maskSettings.visible && maskVideo && maskVideo.readyState >= 2) {
      ctx.globalAlpha = maskSettings.opacity / 100
      ctx.globalCompositeOperation = BLEND_MAP[maskSettings.blendMode] || 'source-over'
      ctx.drawImage(maskVideo, 0, 0, canvas.width, canvas.height)
      // 복원
      ctx.globalAlpha = 1
      ctx.globalCompositeOperation = 'source-over'
    }
  }, [viewingOverlay, viewingMosaic, maskSettings.visible, maskSettings.opacity, maskSettings.blendMode])

  // drawFrame의 최신 참조를 항상 유지 (렌더 루프에서 사용)
  useEffect(() => {
    drawFrameRef.current = drawFrame
  }, [drawFrame])

  // playbackRate ref 동기화
  useEffect(() => {
    playbackRateRef.current = playbackRate
  }, [playbackRate])

  // 모자이크/오버레이 전환 시 현재 시간 저장 및 복원
  useEffect(() => {
    const sourceVideo = sourceVideoRef.current
    const maskVideo = maskVideoRef.current
    const mosaicVideo = mosaicVideoRef.current
    const overlayVideo = overlayVideoRef.current

    // 모드 전환 시 오류 방지를 위해 무조건 일시 정지
    setIsPlaying(false)
    stopRenderLoop()

    if (viewingOverlay) {
      // 오버레이 모드로 전환: source 비디오 일시 정지 및 현재 시간 저장
      if (sourceVideo) {
        sourceVideo.pause()
        if (maskVideo) maskVideo.pause()
        savedTimeRef.current = sourceVideo.currentTime
      }
    } else if (viewingMosaic) {
      // 모자이크 모드로 전환: source 비디오 일시 정지 및 현재 시간 저장
      if (sourceVideo) {
        sourceVideo.pause()
        if (maskVideo) maskVideo.pause()
        savedTimeRef.current = sourceVideo.currentTime
      }
    } else {
      // 일반 모드로 전환: overlay/mosaic 비디오 일시 정지 및 현재 시간으로 source/mask 복원
      if (overlayVideo) overlayVideo.pause()
      if (mosaicVideo) mosaicVideo.pause()

      // 이전 모드에서 현재 시간 가져오기
      const targetTime = overlayVideo?.currentTime || mosaicVideo?.currentTime || savedTimeRef.current

      if (targetTime >= 0 && sourceVideo && maskVideo) {
        savedTimeRef.current = targetTime

        // source와 mask 모두 seek 후 캔버스 그리기
        let sourceReady = false
        let maskReady = false

        const tryDraw = () => {
          if (sourceReady && maskReady) {
            setCurrentTime(targetTime)
            onTimeUpdate?.(targetTime)
            requestAnimationFrame(() => drawFrameRef.current?.())
          }
        }

        sourceVideo.currentTime = targetTime
        sourceVideo.addEventListener('seeked', function onSeeked() {
          sourceVideo.removeEventListener('seeked', onSeeked)
          sourceReady = true
          tryDraw()
        }, { once: true })

        // 퍼센트 기반 동기화: 비율로 계산
        maskVideo.currentTime = targetTime * durationRatioRef.current
        maskVideo.addEventListener('seeked', function onSeeked() {
          maskVideo.removeEventListener('seeked', onSeeked)
          maskReady = true
          tryDraw()
        }, { once: true })
      }
    }
  }, [viewingMosaic, viewingOverlay])

  // 두 비디오가 모두 seek 완료된 후 캔버스를 갱신하는 헬퍼
  const drawAfterSeek = () => {
    // 오버레이 모드일 때는 overlay 비디오의 seeked 이벤트만 감지
    if (viewingOverlay) {
      const overlay = overlayVideoRef.current
      if (!overlay) return
      overlay.addEventListener('seeked', function onSeeked() {
        overlay.removeEventListener('seeked', onSeeked)
        drawFrameRef.current?.()
      })
      return
    }

    // 모자이크 모드일 때는 mosaic 비디오의 seeked 이벤트만 감지
    if (viewingMosaic) {
      const mosaic = mosaicVideoRef.current
      if (!mosaic) return
      mosaic.addEventListener('seeked', function onSeeked() {
        mosaic.removeEventListener('seeked', onSeeked)
        drawFrameRef.current?.()
      })
      return
    }

    const source = sourceVideoRef.current
    const mask = maskVideoRef.current
    if (!source) return

    let sourceReady = false
    let maskReady = !mask // 마스크가 없으면 바로 ready

    const tryDraw = () => {
      if (sourceReady && maskReady) {
        drawFrameRef.current?.()
      }
    }

    source.addEventListener('seeked', function onSeeked() {
      source.removeEventListener('seeked', onSeeked)
      sourceReady = true
      tryDraw()
    })

    if (mask) {
      mask.addEventListener('seeked', function onSeeked() {
        mask.removeEventListener('seeked', onSeeked)
        maskReady = true
        tryDraw()
      })
    }
  }

  // ref를 통해 외부에서 함수 호출 가능하게
  useImperativeHandle(ref, () => ({
    seekFrames: (frames) => {
      const fps = fpsRef.current
      const seekTime = frames / fps
      // 오버레이/모자이크/일반 모드에 따라 활성 비디오 결정
      const activeVideo = viewingOverlay
        ? overlayVideoRef.current
        : viewingMosaic
          ? mosaicVideoRef.current
          : sourceVideoRef.current
      const maskVideo = maskVideoRef.current
      if (activeVideo) {
        const newTime = Math.max(0, Math.min(activeVideo.duration, activeVideo.currentTime + seekTime))

        // 재생 중이면 일시 정지하여 정확한 seek 보장 (일반 모드일 때만)
        const wasPlaying = !activeVideo.paused
        if (wasPlaying && !viewingMosaic && !viewingOverlay) {
          activeVideo.pause()
          maskVideo?.pause()
          stopRenderLoop()
          setIsPlaying(false)
        }

        activeVideo.currentTime = newTime
        // 퍼센트 기반 동기화: 비율로 계산 (일반 모드일 때만)
        if (!viewingMosaic && !viewingOverlay && maskVideo) {
          maskVideo.currentTime = newTime * durationRatioRef.current
        }
        if (activeVideo.paused) drawAfterSeek()
      }
    },
    seekToTime: (targetTime) => {
      // 오버레이/모자이크/일반 모드에 따라 활성 비디오 결정
      const activeVideo = viewingOverlay
        ? overlayVideoRef.current
        : viewingMosaic
          ? mosaicVideoRef.current
          : sourceVideoRef.current
      const maskVideo = maskVideoRef.current
      if (activeVideo) {
        // 재생 중이면 일시 정지하여 정확한 seek 보장 (일반 모드일 때만)
        const wasPlaying = !activeVideo.paused
        if (wasPlaying && !viewingMosaic && !viewingOverlay) {
          activeVideo.pause()
          maskVideo?.pause()
          stopRenderLoop()
          setIsPlaying(false)
        }

        activeVideo.currentTime = targetTime
        // 퍼센트 기반 동기화: source와 mask의 길이가 다를 수 있으므로 비율로 계산 (일반 모드일 때만)
        if (!viewingMosaic && !viewingOverlay && maskVideo) {
          maskVideo.currentTime = targetTime * durationRatioRef.current
        }

        setCurrentTime(targetTime)
        onTimeUpdate?.(targetTime)

        if (activeVideo.paused) drawAfterSeek()
      }
    },
    getCurrentFrame: () => {
      // 오버레이/모자이크/일반 모드에 따라 활성 비디오 결정
      const activeVideo = viewingOverlay
        ? overlayVideoRef.current
        : viewingMosaic
          ? mosaicVideoRef.current
          : sourceVideoRef.current
      if (activeVideo) {
        return Math.floor(activeVideo.currentTime * fpsRef.current)
      }
      return 0
    },
    togglePlay: () => {
      togglePlay()
    }
  }))

  // 비디오 변경 시 로딩 상태 초기화 및 변환 표시 (500ms 이상 로딩 시) + FPS 조회
  useEffect(() => {
    if (currentVideo) {
      // 재생 중지
      setIsPlaying(false)
      stopRenderLoop()

      // 재시도 카운터 초기화
      retryCountRef.current = 0
      setRetryCount(0)
      if (retryTimerRef.current) clearInterval(retryTimerRef.current)

      // Source 비디오 로딩 상태 초기화
      sourceLoadedRef.current = false
      setSourceConverting(false)
      if (sourceLoadTimerRef.current) clearTimeout(sourceLoadTimerRef.current)
      sourceLoadTimerRef.current = setTimeout(() => {
        if (!sourceLoadedRef.current) {
          setSourceConverting(true)
          // 변환 중일 때 1.5초마다 재시도 (최대 30회 = 45초)
          retryTimerRef.current = setInterval(() => {
            if (!sourceLoadedRef.current && retryCountRef.current < 30) {
              retryCountRef.current++
              setRetryCount(retryCountRef.current)
              console.log(`Retrying source video load... (${retryCountRef.current}/30)`)
              // src를 다시 설정하여 재로드
              const sourceVideo = sourceVideoRef.current
              if (sourceVideo) {
                const src = sourceVideo.src
                sourceVideo.src = ''
                sourceVideo.src = src
                sourceVideo.load()
              }
            } else if (sourceLoadedRef.current || retryCountRef.current >= 30) {
              if (retryTimerRef.current) clearInterval(retryTimerRef.current)
              if (retryCountRef.current >= 30) {
                console.error('Source video load timed out after 30 retries')
                setSourceConverting(false)
                setDebugInfo('Source video load timeout! 변환 시간 초과 (다른 비디오가 변환 중일 수 있습니다)')
              }
            }
          }, 1500)
        }
      }, 500)

      // Mask 비디오 로딩 상태 초기화
      maskLoadedRef.current = false
      setMaskConverting(false)
      if (maskLoadTimerRef.current) clearTimeout(maskLoadTimerRef.current)
      maskLoadTimerRef.current = setTimeout(() => {
        if (!maskLoadedRef.current) {
          setMaskConverting(true)
        }
      }, 500)

      // 실제 FPS 조회
      fetch(`/api/video-meta/${currentVideo.name}`)
        .then(res => res.json())
        .then(data => {
          if (data.fps) {
            fpsRef.current = data.fps
          }
          if (data.maskFps && data.maskFps > 0) {
            maskFpsRef.current = data.maskFps
          }
        })
        .catch(() => {
          fpsRef.current = 30
          maskFpsRef.current = 30
        })
    }
    return () => {
      if (sourceLoadTimerRef.current) clearTimeout(sourceLoadTimerRef.current)
      if (maskLoadTimerRef.current) clearTimeout(maskLoadTimerRef.current)
      if (retryTimerRef.current) clearInterval(retryTimerRef.current)
    }
  }, [currentVideo])

  // selectedMaskSource 변경 시 마스크 로딩 상태 리셋
  useEffect(() => {
    if (selectedMaskSource && currentVideo) {
      // Mask 비디오 로딩 상태 초기화
      maskLoadedRef.current = false
      setMaskConverting(false)
      if (maskLoadTimerRef.current) clearTimeout(maskLoadTimerRef.current)
      maskLoadTimerRef.current = setTimeout(() => {
        if (!maskLoadedRef.current) {
          setMaskConverting(true)
        }
      }, 500)
    }
    return () => {
      if (maskLoadTimerRef.current) clearTimeout(maskLoadTimerRef.current)
    }
  }, [selectedMaskSource, currentVideo])

  useEffect(() => {
    const sourceVideo = sourceVideoRef.current
    const maskVideo = maskVideoRef.current

    if (!sourceVideo || !maskVideo) return

    const handleSourceMetadata = () => {
      const dur = sourceVideo.duration
      const fps = fpsRef.current
      setDuration(dur)
      onMetadataLoaded?.({
        frameCount: Math.floor(dur * fps),
        fps: fps,
        duration: dur
      })
      // duration 비율 계산 및 저장
      if (maskVideo.duration && maskVideo.duration > 0) {
        durationRatioRef.current = maskVideo.duration / dur
        console.log(`[Sync] Duration ratio: ${durationRatioRef.current.toFixed(4)} (mask: ${maskVideo.duration.toFixed(2)}s, source: ${dur.toFixed(2)}s)`)
      }
      updateDebugInfo()
      // 메타데이터 로드 후 초기 프레임 그리기
      requestAnimationFrame(() => drawFrameRef.current?.())
    }

    const handleTimeUpdate = () => {
      setCurrentTime(sourceVideo.currentTime)
      onTimeUpdate?.(sourceVideo.currentTime)
    }

    const handleEnded = () => {
      setIsPlaying(false)
      stopRenderLoop()
    }

    const handleError = (e) => {
      console.error('Video error:', e)
      const target = e.target
      if (target === sourceVideo) {
        sourceLoadedRef.current = true
        if (sourceLoadTimerRef.current) clearTimeout(sourceLoadTimerRef.current)
        if (retryTimerRef.current) clearInterval(retryTimerRef.current)
        setSourceConverting(false)
        setRetryCount(0)
        setDebugInfo('Source video error! 비디오를 불러올 수 없습니다.')
      } else if (target === maskVideo) {
        maskLoadedRef.current = true
        if (maskLoadTimerRef.current) clearTimeout(maskLoadTimerRef.current)
        setMaskConverting(false)
        setDebugInfo('Mask video error! 마스크를 불러올 수 없습니다.')
      }
    }

    const handleMaskReady = () => {
      maskLoadedRef.current = true
      if (maskLoadTimerRef.current) clearTimeout(maskLoadTimerRef.current)
      setMaskConverting(false)
      // duration 비율 계산 및 저장
      if (sourceVideo.duration && sourceVideo.duration > 0 && maskVideo.duration > 0) {
        durationRatioRef.current = maskVideo.duration / sourceVideo.duration
        console.log(`[Sync] Duration ratio: ${durationRatioRef.current.toFixed(4)} (mask: ${maskVideo.duration.toFixed(2)}s, source: ${sourceVideo.duration.toFixed(2)}s)`)
      }
      updateDebugInfo()
      // 마스크 로드 완료 후 캔버스 갱신
      requestAnimationFrame(() => drawFrameRef.current?.())
      // 마스크 로드 완료 콜백 호출
      onMaskLoaded?.()
    }

    // 소스 비디오 데이터 준비 시에도 캔버스 갱신 + 디버그 정보 업데이트
    const handleSourceData = () => {
      sourceLoadedRef.current = true
      if (sourceLoadTimerRef.current) clearTimeout(sourceLoadTimerRef.current)
      if (retryTimerRef.current) clearInterval(retryTimerRef.current)
      setSourceConverting(false)
      setRetryCount(0)
      console.log(`Source video loaded successfully (retries: ${retryCountRef.current})`)
      updateDebugInfo()
      requestAnimationFrame(() => drawFrameRef.current?.())
    }

    sourceVideo.addEventListener('loadedmetadata', handleSourceMetadata)
    sourceVideo.addEventListener('loadeddata', handleSourceData)
    sourceVideo.addEventListener('timeupdate', handleTimeUpdate)
    sourceVideo.addEventListener('ended', handleEnded)
    sourceVideo.addEventListener('error', handleError)
    maskVideo.addEventListener('error', handleError)
    maskVideo.addEventListener('loadeddata', handleMaskReady)

    // 소스가 이미 로드 완료된 경우 (캐시 등으로 이벤트를 놓친 경우)
    if (sourceVideo.readyState >= 2) {
      handleSourceData()
    }

    // 마스크가 이미 로드 완료된 경우 (캐시 등으로 이벤트를 놓친 경우)
    if (maskVideo.readyState >= 2) {
      handleMaskReady()
    }

    return () => {
      sourceVideo.removeEventListener('loadedmetadata', handleSourceMetadata)
      sourceVideo.removeEventListener('loadeddata', handleSourceData)
      sourceVideo.removeEventListener('timeupdate', handleTimeUpdate)
      sourceVideo.removeEventListener('ended', handleEnded)
      sourceVideo.removeEventListener('error', handleError)
      maskVideo.removeEventListener('error', handleError)
      maskVideo.removeEventListener('loadeddata', handleMaskReady)
    }
  }, [currentVideo])

  const updateDebugInfo = () => {
    const srcReady = sourceVideoRef.current?.readyState >= 2
    const maskReady = maskVideoRef.current?.readyState >= 2
    setDebugInfo(`Source: ${srcReady ? '✓' : '✗'} | Mask: ${maskReady ? '✓' : '✗'} | Base FPS: ${fpsRef.current}`)
  }

  // maskSettings 변경 시 일시정지 상태에서도 캔버스 즉시 갱신
  useEffect(() => {
    updateDebugInfo()
    requestAnimationFrame(() => drawFrame())
  }, [maskSettings.opacity, maskSettings.visible, maskSettings.blendMode, drawFrame])

  // 재생 속도 변경 (동기화 보장)
  const changePlaybackRate = (rate) => {
    const sourceVideo = sourceVideoRef.current
    const maskVideo = maskVideoRef.current
    const mosaicVideo = mosaicVideoRef.current
    const overlayVideo = overlayVideoRef.current
    const wasPlaying = isPlaying

    setPlaybackRate(rate)
    playbackRateRef.current = rate  // ref도 업데이트

    // 오버레이 모드
    if (viewingOverlay) {
      if (overlayVideo) overlayVideo.playbackRate = rate
      return
    }

    // 모자이크 모드
    if (viewingMosaic) {
      if (mosaicVideo) mosaicVideo.playbackRate = rate
      return
    }

    if (sourceVideo) sourceVideo.playbackRate = rate
    if (maskVideo) {
      // mask는 source보다 짧으므로 더 느리게 재생해야 동기화됨
      maskVideo.playbackRate = rate * durationRatioRef.current

      // 재생 중이 아니면 동기화 재확인 (일반 모드일 때만)
      if (!wasPlaying) {
        // 퍼센트 기반 동기화: 비율로 계산
        maskVideo.currentTime = sourceVideo.currentTime * durationRatioRef.current
        requestAnimationFrame(() => drawFrame())
      }
    }
  }

  // rAF 기반 Canvas 렌더 루프 + 실시간 FPS 측정
  const startRenderLoop = () => {
    let lastSourceTime = sourceVideoRef.current?.currentTime || 0
    let lastMaskTime = maskVideoRef.current?.currentTime || 0
    let sourceFrameCount = 0
    let maskFrameCount = 0
    let lastFpsUpdate = performance.now()

    const render = () => {
      const source = sourceVideoRef.current
      const mask = maskVideoRef.current
      const mosaic = mosaicVideoRef.current
      const overlay = overlayVideoRef.current

      // 오버레이/모자이크/일반 모드에 따라 활성 비디오 결정
      const activeVideo = viewingOverlay ? overlay : viewingMosaic ? mosaic : source
      if (activeVideo && !activeVideo.paused) {
        const now = performance.now()

        if (!viewingMosaic && !viewingOverlay) {
          // 실시간 FPS 측정: currentTime 변화 감지 (source+mask 모드)
          if (source && source.currentTime !== lastSourceTime) {
            sourceFrameCount++
            lastSourceTime = source.currentTime
          }
          if (mask && mask.currentTime !== lastMaskTime) {
            maskFrameCount++
            lastMaskTime = mask.currentTime
          }

          // 0.5초마다 FPS 업데이트
          if (now - lastFpsUpdate >= 500) {
            const elapsed = (now - lastFpsUpdate) / 1000
            const sFps = Math.round(sourceFrameCount / elapsed)
            const mFps = Math.round(maskFrameCount / elapsed)
            setLiveFps({ source: sFps, mask: mFps })
            sourceFrameCount = 0
            maskFrameCount = 0
            lastFpsUpdate = now
          }

          // 마스크 동기화: 퍼센트 기반 스마트 동기화 (playbackRate 조정 + 필요시 seek)
          if (mask && source) {
            // 퍼센트 기반 목표 위치: source 시간에 비율 적용
            const maskTargetTime = source.currentTime * durationRatioRef.current
            const diff = mask.currentTime - maskTargetTime
            const absDiff = Math.abs(diff)
            const frameDuration = 1 / maskFpsRef.current
            // mask의 기본 재생 속도는 source 속도 * 비율
            const maskBaseRate = playbackRateRef.current * durationRatioRef.current

            // 큰 차이(3프레임 이상)는 seek로 해결 (하지만 너무 자주 하지 않음)
            const timeSinceLastSeek = now - lastSyncSeekRef.current
            if (absDiff > (3 * frameDuration) && timeSinceLastSeek > 1000) {
              mask.currentTime = maskTargetTime
              lastSyncSeekRef.current = now
              // seek 후에는 기본 속도로 복원
              mask.playbackRate = maskBaseRate
            }
            // 작은 차이(0.5~3프레임)는 playbackRate로 부드럽게 조정
            else if (absDiff > (0.5 * frameDuration) && absDiff <= (3 * frameDuration)) {
              if (diff > 0) {
                // mask가 앞서가면 느리게
                mask.playbackRate = maskBaseRate * 0.98
              } else {
                // mask가 뒤처지면 빠르게
                mask.playbackRate = maskBaseRate * 1.02
              }
            }
            // 차이가 거의 없으면 원래 속도로
            else if (absDiff <= (0.5 * frameDuration)) {
              mask.playbackRate = maskBaseRate
            }
          }
        }

        // Canvas에 프레임 그리기 (최신 drawFrame 참조 사용)
        drawFrameRef.current?.()

        renderAnimRef.current = requestAnimationFrame(render)
      }
    }
    renderAnimRef.current = requestAnimationFrame(render)
  }

  const stopRenderLoop = () => {
    if (renderAnimRef.current) {
      cancelAnimationFrame(renderAnimRef.current)
      renderAnimRef.current = null
    }
    setLiveFps({ source: 0, mask: 0 })
    // 정지 시 mask playbackRate 복원 (비율 적용)
    const maskVideo = maskVideoRef.current
    if (maskVideo) {
      maskVideo.playbackRate = playbackRateRef.current * durationRatioRef.current
    }
  }

  const togglePlay = () => {
    // 오버레이 모드
    if (viewingOverlay) {
      const overlayVideo = overlayVideoRef.current
      if (!overlayVideo) return
      if (isPlaying) {
        overlayVideo.pause()
        stopRenderLoop()
        requestAnimationFrame(() => drawFrame())
      } else {
        overlayVideo.play()
        startRenderLoop()
      }
      setIsPlaying(!isPlaying)
      return
    }

    // 모자이크 모드
    if (viewingMosaic) {
      const mosaicVideo = mosaicVideoRef.current
      if (!mosaicVideo) return
      if (isPlaying) {
        mosaicVideo.pause()
        stopRenderLoop()
        requestAnimationFrame(() => drawFrame())
      } else {
        mosaicVideo.play()
        startRenderLoop()
      }
      setIsPlaying(!isPlaying)
      return
    }

    const sourceVideo = sourceVideoRef.current
    const maskVideo = maskVideoRef.current

    // 퍼센트 기반 동기화: source 시간에 비율 적용
    const getTargetMaskTime = () => {
      return sourceVideo.currentTime * durationRatioRef.current
    }

    if (isPlaying) {
      sourceVideo.pause()
      maskVideo.pause()
      stopRenderLoop()

      // 일시정지 시 동기화 확인 (다음 재생 시 깜빡임 방지)
      const targetMaskTime = getTargetMaskTime()
      const currentDiff = Math.abs(maskVideo.currentTime - targetMaskTime)
      const fps = fpsRef.current || 30
      const oneFrameDuration = 1 / fps

      // 1프레임 이상 차이나면 동기화 (일시정지 상태이므로 seek해도 깜빡임 없음)
      if (currentDiff > oneFrameDuration && maskVideo.readyState >= 2) {
        maskVideo.currentTime = targetMaskTime
      }

      // 일시정지 후 현재 프레임 다시 그리기
      requestAnimationFrame(() => drawFrame())
    } else {
      // 재생 전 동기화 확인
      const targetMaskTime = getTargetMaskTime()
      const currentDiff = Math.abs(maskVideo.currentTime - targetMaskTime)
      const fps = fpsRef.current || 30
      const oneFrameDuration = 1 / fps

      // playbackRate를 기본값으로 재설정 (mask는 비율 적용)
      const currentRate = playbackRateRef.current
      sourceVideo.playbackRate = currentRate
      maskVideo.playbackRate = currentRate * durationRatioRef.current

      // 마지막 seek 시간 초기화
      lastSyncSeekRef.current = 0

      // 재생 시작 함수
      const startPlayback = () => {
        sourceVideo.play()
        maskVideo.play()
        startRenderLoop()
        setIsPlaying(true)
      }

      // 동기화가 충분히 잘 되어 있으면 (1프레임 이내) seek 없이 바로 재생
      if (currentDiff <= oneFrameDuration) {
        startPlayback()
      } else {
        // 동기화가 필요한 경우에만 seek 수행
        maskVideo.currentTime = targetMaskTime
        maskVideo.addEventListener('seeked', function onSeeked() {
          maskVideo.removeEventListener('seeked', onSeeked)
          startPlayback()
        }, { once: true })
      }
      return
    }
    setIsPlaying(!isPlaying)
  }

  const handleTimelineChange = (e) => {
    const percent = e.target.value / 100
    const newTime = percent * duration

    // 오버레이 모드
    if (viewingOverlay) {
      const overlayVideo = overlayVideoRef.current
      if (overlayVideo) {
        overlayVideo.currentTime = newTime
        drawAfterSeek()
      }
      return
    }

    // 모자이크 모드
    if (viewingMosaic) {
      const mosaicVideo = mosaicVideoRef.current
      if (mosaicVideo) {
        mosaicVideo.currentTime = newTime
        drawAfterSeek()
      }
    } else {
      const sourceVideo = sourceVideoRef.current
      const maskVideo = maskVideoRef.current

      // 재생 중이면 일시 정지 후 seek
      const wasPlaying = isPlaying
      if (wasPlaying) {
        sourceVideo.pause()
        maskVideo.pause()
        stopRenderLoop()
        setIsPlaying(false)
      }

      sourceVideo.currentTime = newTime
      // 퍼센트 기반 동기화: 비율로 계산
      if (maskVideo) {
        maskVideo.currentTime = newTime * durationRatioRef.current
      }
      drawAfterSeek()
    }
  }

  const formatTime = (seconds) => {
    if (isNaN(seconds)) return '00:00'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0

  const handleEvaluationClick = async (filename) => {
    if (selectedEvaluation === filename) {
      setSelectedEvaluation(null)
      setEvaluationDetails(null)
      return
    }

    try {
      const response = await fetch(`/api/evaluations/${filename}`)
      const data = await response.json()
      setSelectedEvaluation(filename)
      setEvaluationDetails(data.results)
    } catch (err) {
      console.error('Failed to load evaluation details:', err)
    }
  }

  // 특정 프레임으로 이동
  const handleFrameClick = (frame) => {
    if (frame === null || frame === undefined) return

    if (onSeekToFrame) {
      onSeekToFrame(frame)
    }
  }

  return (
    <div className="main-content">
      <div className="video-header">
        <h1>{currentVideo?.source || 'No video selected'}</h1>
        <span className={`badge ${viewingMosaic ? 'badge-mosaic' : viewingOverlay ? 'badge-overlay' : ''}`}>
          {viewingOverlay ? '🎬 Overlay' : viewingMosaic ? '🎬 Mosaic' : 'Source + Mask'}
        </span>
      </div>

      <div className="video-container">
        {/* 히든 비디오 소스들 (Canvas 렌더링 소스로만 사용) */}
        <video
          ref={sourceVideoRef}
          src={currentVideo
            ? (videoUrls.source || `/video/source/${currentVideo.source}`)
            : ''}
          crossOrigin="anonymous"
          muted
          playsInline
          preload="auto"
        />
        <video
          ref={maskVideoRef}
          src={currentVideo && selectedMaskSource
            ? (videoUrls.mask || `/video/masks/${selectedMaskSource}/${currentVideo.mask}`)
            : ''}
          crossOrigin="anonymous"
          muted
          playsInline
          preload="auto"
        />
        {/* 모자이크 비디오 (모자이크 모드일 때만 로드) */}
        {viewingMosaic && currentVideo && (
          <video
            ref={mosaicVideoRef}
            src={selectedMaskSource
              ? `/video/mosaic/${selectedMaskSource}/${currentVideo.name.replace(/_\d+$/, '')}/${currentVideo.name}.mp4`
              : `/video/mosaic/${currentVideo.name.replace(/_\d+$/, '')}/${currentVideo.name}.mp4`
            }
            crossOrigin="anonymous"
            muted
            playsInline
            preload="auto"
            onLoadedData={() => {
              const mv = mosaicVideoRef.current
              if (mv) {
                setDuration(mv.duration)
                onMetadataLoaded?.({
                  frameCount: Math.floor(mv.duration * fpsRef.current),
                  fps: fpsRef.current,
                  duration: mv.duration
                })

                // 저장된 시간으로 seek (모자이크 전환 시 현재 프레임 유지)
                const targetTime = savedTimeRef.current >= 0 ? savedTimeRef.current : 0
                if (Math.abs(mv.currentTime - targetTime) > 0.01) {
                  // seek가 필요한 경우 seeked 이벤트를 기다림
                  mv.currentTime = targetTime
                  mv.addEventListener('seeked', function onSeeked() {
                    mv.removeEventListener('seeked', onSeeked)
                    setCurrentTime(targetTime)
                    onTimeUpdate?.(targetTime)
                    requestAnimationFrame(() => drawFrame())
                  }, { once: true })
                } else {
                  // 이미 올바른 위치에 있으면 바로 그리기
                  setCurrentTime(targetTime)
                  onTimeUpdate?.(targetTime)
                  requestAnimationFrame(() => drawFrame())
                }
              }
            }}
            onTimeUpdate={() => {
              const mv = mosaicVideoRef.current
              if (mv) {
                setCurrentTime(mv.currentTime)
                onTimeUpdate?.(mv.currentTime)
              }
            }}
            onEnded={() => {
              setIsPlaying(false)
              stopRenderLoop()
            }}
          />
        )}
        {/* 오버레이 비디오 (오버레이 모드일 때만 로드) */}
        {viewingOverlay && currentVideo && (
          <video
            ref={overlayVideoRef}
            src={selectedMaskSource
              ? `/video/overlay/${selectedMaskSource}/${currentVideo.name.replace(/_\d+$/, '')}/${currentVideo.name}.mp4`
              : `/video/overlay/${currentVideo.name.replace(/_\d+$/, '')}/${currentVideo.name}.mp4`
            }
            crossOrigin="anonymous"
            muted
            playsInline
            preload="auto"
            onLoadedData={() => {
              const ov = overlayVideoRef.current
              if (ov) {
                setDuration(ov.duration)
                onMetadataLoaded?.({
                  frameCount: Math.floor(ov.duration * fpsRef.current),
                  fps: fpsRef.current,
                  duration: ov.duration
                })

                // 저장된 시간으로 seek (오버레이 전환 시 현재 프레임 유지)
                const targetTime = savedTimeRef.current >= 0 ? savedTimeRef.current : 0
                if (Math.abs(ov.currentTime - targetTime) > 0.01) {
                  ov.currentTime = targetTime
                  ov.addEventListener('seeked', function onSeeked() {
                    ov.removeEventListener('seeked', onSeeked)
                    setCurrentTime(targetTime)
                    onTimeUpdate?.(targetTime)
                    requestAnimationFrame(() => drawFrame())
                  }, { once: true })
                } else {
                  setCurrentTime(targetTime)
                  onTimeUpdate?.(targetTime)
                  requestAnimationFrame(() => drawFrame())
                }
              }
            }}
            onTimeUpdate={() => {
              const ov = overlayVideoRef.current
              if (ov) {
                setCurrentTime(ov.currentTime)
                onTimeUpdate?.(ov.currentTime)
              }
            }}
            onEnded={() => {
              setIsPlaying(false)
              stopRenderLoop()
            }}
          />
        )}
        {/* Canvas: 소스 + 마스크 합성 렌더링 */}
        <canvas ref={canvasRef} className="composite-canvas" />
        {videoPreparing && (
          <div className="source-converting">
            ⏳ 비디오 준비 중... (변환이 필요하면 시간이 걸릴 수 있습니다)
          </div>
        )}
        {sourceConverting && !videoPreparing && (
          <div className="source-converting">
            ⏳ 소스 비디오 변환 중... {retryCount > 0 && `(${retryCount}/30)`}
            {retryCount > 10 && (
              <div style={{ fontSize: '11px', marginTop: '4px', opacity: 0.8 }}>
                다른 비디오 변환 대기 중일 수 있습니다
              </div>
            )}
          </div>
        )}
        {maskConverting && (
          <div className="mask-converting">
            ⏳ 마스크 비디오 변환 중...
          </div>
        )}
        <div className="debug-info">
          {debugInfo}
          {isPlaying && liveFps.source > 0 && (
            <span> | Source FPS: <strong>{liveFps.source}</strong> | Mask FPS: <strong>{liveFps.mask}</strong></span>
          )}
        </div>
      </div>

      <div className="video-controls">
        <button className="play-btn" onClick={togglePlay}>
          {isPlaying ? '⏸' : '▶'}
        </button>
        <input
          type="range"
          className="timeline"
          min="0"
          max="100"
          value={progress}
          onChange={handleTimelineChange}
        />
        <span className="time-display">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>

      {/* 재생 속도 조절 */}
      <div className="speed-controls">
        {PLAYBACK_RATES.map(rate => (
          <button
            key={rate}
            className={`speed-btn ${playbackRate === rate ? 'active' : ''}`}
            onClick={() => changePlaybackRate(rate)}
          >
            {rate}x
          </button>
        ))}
      </div>

      {evaluationHistory.length > 0 && (
        <div className="evaluation-history">
          <h4>평가 기록</h4>
          <ul>
            {evaluationHistory.map((item, index) => (
              <li
                key={index}
                className={selectedEvaluation === item.filename ? 'selected' : ''}
                onClick={() => handleEvaluationClick(item.filename)}
              >
                <span className="history-filename">{item.filename}</span>
                <span className="history-date">
                  {new Date(item.created).toLocaleString('ko-KR')}
                </span>
              </li>
            ))}
          </ul>

          {evaluationDetails && (
            <div className="evaluation-details">
              <div className="eval-detail-actions">
                <button
                  className="load-eval-btn"
                  onClick={() => onLoadEvaluation?.(selectedEvaluation)}
                >
                  이 평가 불러오기
                </button>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>카테고리</th>
                    <th>질문</th>
                    <th>결과</th>
                    <th>프레임</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluationDetails.map((row, index) => (
                    <tr key={index}>
                      <td>{row.id}</td>
                      <td>{row.category}</td>
                      <td className="question-cell">{row.question}</td>
                      <td className={row.result === 'O' ? 'pass' : row.result === 'X' ? 'fail' : ''}>
                        {row.result}
                      </td>
                      <td>
                        {row.frameRanges && row.frameRanges.length > 0 ? (
                          <div className="frame-ranges-list">
                            {row.frameRanges.map((range, idx) => (
                              <span
                                key={idx}
                                className="frame-range-badge"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleFrameClick(range.start)
                                }}
                                title="클릭하면 해당 프레임으로 이동"
                              >
                                {range.start}{range.start !== range.end ? `~${range.end}` : ''}
                              </span>
                            ))}
                          </div>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
})

export default VideoPlayer
