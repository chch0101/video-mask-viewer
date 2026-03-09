import { memo } from 'react'

const QUESTIONS = [
  {
    section: 'No.1 객체 완전성',
    items: [
      { id: 'Q1', text: '객체가 여러 영역으로 분할되지 않고 단일 마스크로 온전하게 검출되는가?' },
      { id: 'Q2', text: '영상 내 식별 가능한 모든 객체에 대해 누락 없이 마스크가 생성되었는가?' },
    ]
  },
  {
    section: 'No.2 마스크 정확성',
    items: [
      { id: 'Q3', text: '인식 대상이 아닌 객체에 대해 마스크가 잘못 생성되지 않았는가?' },
    ]
  },
  {
    section: 'No.3 경계 정밀도',
    items: [
      { id: 'Q4', text: '생성된 마스크가 실제 객체의 경계선을 따르는가?' }
    ]
  },
  {
    section: 'No.4 시간적 안정성',
    items: [
      { id: 'Q5', text: '영상이 재생되는 동안 마스크가 깜빡거리거나 순간적으로 사라지는 현상이 없는가?' }
    ]
  }
]

const EvaluationPanel = memo(function EvaluationPanel({
  evaluations,
  onEvaluate,
  onAddFrameRange,
  onUpdateFrameRange,
  onRemoveFrameRange,
  onSave,
  getCurrentFrame,
  isSaving
}) {
  const completed = Object.values(evaluations).filter(v => v.result !== null).length
  const total = 5
  const naCount = total - completed

  // 모든 질문이 범위 기반: O/X 토글 + X일 때 프레임 범위 기록
  const handleEvaluate = (questionId, value) => {
    const currentEval = evaluations[questionId]

    if (currentEval?.result === value) {
      // 선택 해제 시 result만 null로, 프레임 범위는 유지
      onEvaluate(questionId, null)
    } else {
      onEvaluate(questionId, value)
    }
  }

  return (
    <div className="evaluation-panel">
      <h2>Model Evaluation</h2>

      {QUESTIONS.map((section) => (
        <div key={section.section} className="eval-section">
          <h3>{section.section}</h3>
          {section.items.map((item) => {
            const evalData = evaluations[item.id]

            return (
              <div key={item.id} className="eval-item">
                <div className="eval-question">{item.id}. {item.text}</div>

                <div className="eval-buttons">
                  <button
                    className={`eval-btn pass-btn ${evalData.result === 'O' ? 'selected' : ''}`}
                    onClick={() => handleEvaluate(item.id, 'O')}
                  >
                    O
                  </button>
                  <button
                    className={`eval-btn fail-btn ${evalData.result === 'X' ? 'selected' : ''}`}
                    onClick={() => handleEvaluate(item.id, 'X')}
                  >
                    X
                  </button>
                </div>

                {evalData.result === 'X' && (
                  <div className="frame-ranges-container">
                    {evalData.frameRanges.map((range, index) => (
                      <div key={index} className="frame-range-row">
                        <input
                          type="number"
                          className="frame-input"
                          value={range.start}
                          onChange={(e) => onUpdateFrameRange(item.id, index, 'start', parseInt(e.target.value) || 0)}
                          placeholder="시작"
                        />
                        <span className="range-separator">~</span>
                        <input
                          type="number"
                          className="frame-input"
                          value={range.end}
                          onChange={(e) => onUpdateFrameRange(item.id, index, 'end', parseInt(e.target.value) || 0)}
                          placeholder="끝"
                        />
                        <button
                          className="frame-action-btn set-start-btn"
                          onClick={() => onUpdateFrameRange(item.id, index, 'start', getCurrentFrame())}
                          title="현재 프레임을 시작으로"
                        >
                          start
                        </button>
                        <button
                          className="frame-action-btn set-end-btn"
                          onClick={() => onUpdateFrameRange(item.id, index, 'end', getCurrentFrame())}
                          title="현재 프레임을 끝으로"
                        >
                          end
                        </button>
                        <button
                          className="frame-action-btn remove-btn"
                          onClick={() => onRemoveFrameRange(item.id, index)}
                          title="범위 삭제"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                    <button
                      className="add-range-btn"
                      onClick={() => onAddFrameRange(item.id)}
                    >
                      + 범위 추가
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}


      <div className="save-section">
        <div className="progress-bar-container">
          <div
            className="progress-bar-fill"
            style={{ width: `${(completed / total) * 100}%` }}
          />
        </div>
        <div className="progress-info">
          <span>{completed} / {total} 완료</span>
          {naCount > 0 && <span style={{ color: '#999', marginLeft: '8px' }}>({naCount}개 N/A)</span>}
        </div>
        <button
          className="save-btn"
          disabled={isSaving}
          onClick={onSave}
        >
          {isSaving ? '저장 중...' : 'CSV 저장 '}
        </button>
      </div>
    </div >
  )
})

export default EvaluationPanel
