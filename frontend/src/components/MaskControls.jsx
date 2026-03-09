import { memo } from 'react'
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
        style={{ marginBottom: '8px' }}
      >
        {overlayGenerating ? '오버레이 생성 중...' : viewingOverlay ? '실시간 합성 보기' : '오버레이 보기 (권장)'}
      </button>

      <button
        className={`mosaic-toggle-btn ${viewingMosaic ? 'active' : ''}`}
        onClick={onToggleMosaic}
        disabled={mosaicGenerating || viewingOverlay}
      >
        {mosaicGenerating ? '모자이크 생성 중...' : viewingMosaic ? '원본+마스크 보기' : '모자이크 변경'}
      </button>
    </div>
  )
})

export default MaskControls
