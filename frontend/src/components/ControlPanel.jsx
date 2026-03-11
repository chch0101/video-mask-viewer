import { memo, useState, useMemo } from 'react'
import MaskControls from './MaskControls'

const ControlPanel = memo(function ControlPanel({
  user,
  onLogout,
  videos,
  currentVideo,
  currentFrame,
  frameCount,
  fps,
  viewingMosaic,
  mosaicGenerating,
  maskSources = [],
  selectedMaskSource,
  maskSourceLoading = false,
  onMaskSourceChange,
  onVideoSelect,
  onPrevVideo,
  onNextVideo,
  onSeekFrames,
  onToggleMosaic
}) {
  const [selectedTask, setSelectedTask] = useState('all')

  // task 목록 추출 (비디오 이름에서 task 추출: face_0001 → face)
  const tasks = useMemo(() => {
    const taskSet = new Set()
    videos.forEach(video => {
      const parts = video.name.split('_')
      if (parts.length >= 2) {
        const task = parts.slice(0, -1).join('_') // 마지막 숫자 부분 제외
        taskSet.add(task)
      }
    })
    return ['all', ...Array.from(taskSet).sort()]
  }, [videos])

  // 선택된 task에 따라 필터링된 비디오 목록
  const filteredVideos = useMemo(() => {
    if (selectedTask === 'all') {
      return videos
    }
    return videos.filter(video => video.name.startsWith(selectedTask + '_'))
  }, [videos, selectedTask])

  const currentIndex = filteredVideos.findIndex(v => v.name === currentVideo?.name)
  const evaluatedCount = videos.filter(v => v.evaluated).length
  const filteredEvaluatedCount = filteredVideos.filter(v => v.evaluated).length

  const handleTaskChange = (task) => {
    setSelectedTask(task)

    // Task 변경 시 해당 task의 첫 번째 비디오로 자동 전환
    const newFilteredVideos = task === 'all'
      ? videos
      : videos.filter(video => video.name.startsWith(task + '_'))

    if (newFilteredVideos.length > 0) {
      // 현재 비디오가 새로운 필터에 없으면 첫 번째 비디오로 전환
      const isCurrentInFiltered = newFilteredVideos.some(v => v.name === currentVideo?.name)
      if (!isCurrentInFiltered) {
        onVideoSelect(newFilteredVideos[0].name)
      }
    }
  }

  return (
    <div className="control-panel" style={{ display: 'flex', flexDirection: 'column', gap: '15px', paddingTop: '15px' }}>
      {user && (
        <div style={{ 
          display: 'flex', alignItems: 'center', gap: '10px', 
          backgroundColor: '#f8f9fa', padding: '12px', borderRadius: '8px',
          border: '1px solid #e0e0e0', marginBottom: '5px'
        }}>
          {user.picture && <img src={user.picture} alt="profile" style={{ width: 32, height: 32, borderRadius: '50%' }} />}
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
            <span style={{
              fontWeight: 'bold', fontSize: '14px', lineHeight: '1.2',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'
            }}>{user.name}</span>
            <span style={{ color: '#666', fontSize: '12px' }}>Saved: {user.saved_count || 0}</span>
          </div>
          <button 
            onClick={onLogout} 
            style={{ 
              padding: '6px 10px', cursor: 'pointer', borderRadius: '4px', 
              border: '1px solid #ccc', background: 'white', fontSize: '12px' 
            }}
          >
            Logout
          </button>
        </div>
      )}

      <h2 style={{ marginTop: 0, marginBottom: '5px' }}>Control Panel</h2>

      <div className="control-section">
        <label>Task Filter</label>
        <div className="task-filter-buttons">
          {tasks.map((task) => (
            <button
              key={task}
              className={`task-filter-btn ${selectedTask === task ? 'active' : ''}`}
              onClick={() => handleTaskChange(task)}
            >
              {task === 'all' ? 'All' : task}
            </button>
          ))}
        </div>
      </div>

      <div className="control-section">
        <label>Select Video ({filteredVideos.length})</label>
        <select
          value={currentVideo?.name || ''}
          onChange={(e) => onVideoSelect(e.target.value)}
        >
          {filteredVideos.map((video) => {
            const maskCount = video.availableMasks?.length || 0
            const hasMask = maskCount > 0
            const hasSelectedMask = video.availableMasks?.includes(selectedMaskSource)
            return (
              <option key={video.name} value={video.name}>
                {hasMask ? (hasSelectedMask ? '●' : '○') : '✕'} {video.source} [{maskCount}]
              </option>
            )
          })}
        </select>
      </div>

      {currentVideo && (() => {
        const hasCurrentMask = currentVideo.availableMasks?.includes(selectedMaskSource)
        const hasMasks = currentVideo.availableMasks?.length > 0

        return (
          <div className="info-box" style={{
            background: !hasCurrentMask && hasMasks ? '#fff3e0' : '#e3f2fd',
            borderLeft: `3px solid ${!hasCurrentMask && hasMasks ? '#ff9800' : '#2196f3'}`
          }}>
            <div style={{ fontSize: '11px', color: '#666', marginBottom: '4px' }}>
              Available Masks
            </div>
            {hasMasks ? (
              <>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                  {currentVideo.availableMasks.map(mask => (
                    <span
                      key={mask}
                      style={{
                        padding: '2px 6px',
                        borderRadius: '4px',
                        fontSize: '11px',
                        backgroundColor: mask === selectedMaskSource ? '#1976d2' : '#e0e0e0',
                        color: mask === selectedMaskSource ? '#fff' : '#333',
                        cursor: 'pointer'
                      }}
                      onClick={() => onMaskSourceChange(mask)}
                    >
                      {mask}
                    </span>
                  ))}
                </div>
                {!hasCurrentMask && (
                  <div style={{
                    marginTop: '8px',
                    padding: '6px 8px',
                    background: '#ffecb3',
                    borderRadius: '4px',
                    fontSize: '11px',
                    color: '#e65100'
                  }}>
                    ⚠️ 현재 선택된 '{selectedMaskSource}'에는 마스크가 없습니다.
                    위 태그를 클릭하여 다른 소스를 선택하세요.
                  </div>
                )}
              </>
            ) : (
              <div style={{ color: '#f44336', fontSize: '12px' }}>No masks available</div>
            )}
          </div>
        )
      })()}

      <div className="nav-buttons">
        <button
          onClick={() => {
            if (currentIndex > 0) {
              onVideoSelect(filteredVideos[currentIndex - 1].name)
            }
          }}
          disabled={currentIndex <= 0}
        >
          Prev Video
        </button>
        <button
          onClick={() => {
            if (currentIndex < filteredVideos.length - 1) {
              onVideoSelect(filteredVideos[currentIndex + 1].name)
            }
          }}
          disabled={currentIndex >= filteredVideos.length - 1}
        >
          Next Video
        </button>
      </div>

      <div className="info-box">
        <div>Current: <span style={{ fontWeight: 'bold', color: '#1976d2' }}>{currentFrame + 1}</span> / {frameCount}</div>
        <div>FPS: <span>{fps}</span></div>
      </div>

      <div className="info-box" style={{ background: '#e8f5e9', borderLeft: '3px solid #4caf50' }}>
        <div style={{ fontSize: '11px', color: '#666', marginBottom: '4px' }}>
          {selectedTask === 'all' ? 'All Tasks' : selectedTask}
        </div>
        <div>
          <span style={{ fontWeight: 'bold', color: '#2e7d32' }}>{filteredEvaluatedCount}</span>
          <span> / {filteredVideos.length}</span>
          <span style={{ fontSize: '11px', color: '#666', marginLeft: '6px' }}>evaluated</span>
        </div>
        {selectedTask !== 'all' && (
          <div style={{ fontSize: '11px', color: '#888', marginTop: '4px' }}>
            Total: {evaluatedCount} / {videos.length}
          </div>
        )}
      </div>

      <div className="control-section">
        <label>Frame Navigation</label>
        <div className="frame-controls">
          <button onClick={() => onSeekFrames(-30)}>{"<<"}</button>
          <button onClick={() => onSeekFrames(-1)}>{"<"}</button>
          <button onClick={() => onSeekFrames(1)}>{">"}</button>
          <button onClick={() => onSeekFrames(30)}>{">>"}</button>
        </div>
      </div>

      {maskSources.length > 0 && (
        <div className="control-section">
          <label>
            Mask Source
            {maskSourceLoading && <span className="loading-spinner small"></span>}
          </label>
          <select
            value={selectedMaskSource}
            onChange={(e) => onMaskSourceChange(e.target.value)}
            className={`mask-source-select ${maskSourceLoading ? 'loading' : ''}`}
            disabled={maskSourceLoading}
          >
            {maskSources.map((source) => (
              <option key={source.name} value={source.name}>
                {source.name} ({source.count})
              </option>
            ))}
          </select>
        </div>
      )}

      <MaskControls
        viewingMosaic={viewingMosaic}
        mosaicGenerating={mosaicGenerating}
        onToggleMosaic={onToggleMosaic}
      />
    </div>
  )
})

export default ControlPanel
