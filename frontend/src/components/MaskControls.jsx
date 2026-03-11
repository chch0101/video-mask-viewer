import { memo, useState, useEffect } from 'react'
import { useMask } from '../contexts/MaskContext'

const MaskControls = memo(function MaskControls({
  viewingMosaic,
  mosaicGenerating,
  onToggleMosaic,
  viewingOverlay,
  overlayGenerating,
  onToggleOverlay
}) {
  const { maskSettings, setOpacity, setBlendMode } = useMask()
  const [mosaicElapsed, setMosaicElapsed] = useState(0)
  const [overlayElapsed, setOverlayElapsed] = useState(0)

  // 모자이크 생성 경과 시간 타이머
  useEffect(() => {
    if (mosaicGenerating) {
      setMosaicElapsed(0)
      const timer = setInterval(() => setMosaicElapsed(e => e + 1), 1000)
      return () => clearInterval(timer)
    }
  }, [mosaicGenerating])

  // 오버레이 생성 경과 시간 타이머
  useEffect(() => {
    if (overlayGenerating) {
      setOverlayElapsed(0)
      const timer = setInterval(() => setOverlayElapsed(e => e + 1), 1000)
      return () => clearInterval(timer)
    }
  }, [overlayGenerating])

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return m > 0 ? `${m}분 ${s}초` : `${s}초`
  }

  return (
    <div className="mask-controls">
      <h3>Mask Overlay</h3>
      <div className="mask-toggle">
        <span>Status:</span>
        <span className={`toggle-status ${maskSettings.visible ? 'on' : 'off'}`}>
          {maskSettings.visible ? 'ON' : 'OFF'}
        </span>
      </div>
      <div className="opacity-control">
        <label>
          Opacity
          <span>{maskSettings.opacity}%</span>
        </label>
        <input
          type="range"
          className="opacity-slider"
          min="0"
          max="100"
          value={maskSettings.opacity}
          onChange={(e) => setOpacity(Number(e.target.value))}
        />
      </div>
      <div className="opacity-control" style={{ marginTop: '10px' }}>
        <label>Blend Mode</label>
        <select
          value={maskSettings.blendMode}
          onChange={(e) => setBlendMode(e.target.value)}
          style={{ width: '100%', marginTop: '5px', padding: '6px' }}
        >
          <option value="normal">Normal</option>
          <option value="multiply">Multiply</option>
          <option value="screen">Screen</option>
          <option value="overlay">Overlay</option>
          <option value="difference">Difference</option>
        </select>
      </div>

      <button
        className={`overlay-toggle-btn ${viewingOverlay ? 'active' : ''}`}
        onClick={onToggleOverlay}
        disabled={overlayGenerating || viewingMosaic}
        style={{ marginBottom: '8px', position: 'relative' }}
      >
        {overlayGenerating ? (
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            <span className="spinner" style={{
              width: '14px', height: '14px', border: '2px solid #fff',
              borderTopColor: 'transparent', borderRadius: '50%',
              animation: 'spin 1s linear infinite'
            }} />
            오버레이 생성 중... ({formatTime(overlayElapsed)})
          </span>
        ) : viewingOverlay ? '실시간 합성 보기' : '오버레이 보기 (권장)'}
      </button>

      <button
        className={`mosaic-toggle-btn ${viewingMosaic ? 'active' : ''}`}
        onClick={onToggleMosaic}
        disabled={mosaicGenerating || viewingOverlay}
        style={{ position: 'relative' }}
      >
        {mosaicGenerating ? (
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            <span className="spinner" style={{
              width: '14px', height: '14px', border: '2px solid #fff',
              borderTopColor: 'transparent', borderRadius: '50%',
              animation: 'spin 1s linear infinite'
            }} />
            모자이크 생성 중... ({formatTime(mosaicElapsed)})
          </span>
        ) : viewingMosaic ? '원본+마스크 보기' : '모자이크 변경'}
      </button>

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
})

export default MaskControls
