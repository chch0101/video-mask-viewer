import { useState, useEffect } from 'react'

export default function AdminPanel({ user, onClose }) {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [stats, setStats] = useState({ user_count: 0, eval_count: 0 })
  const [users, setUsers] = useState([])
  const [evaluations, setEvaluations] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedUser, setSelectedUser] = useState('')

  const headers = { 'X-User-Email': user?.email || '' }

  useEffect(() => {
    fetchStats()
    fetchUsers()
  }, [])

  useEffect(() => {
    if (activeTab === 'evaluations') fetchEvaluations()
  }, [activeTab])

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/admin/stats', { headers })
      const data = await res.json()
      setStats(data)
    } catch (err) {
      console.error('Failed to fetch stats:', err)
    }
  }

  const fetchUsers = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/admin/users', { headers })
      const data = await res.json()
      setUsers(data.users || [])
    } catch (err) {
      console.error('Failed to fetch users:', err)
    }
    setLoading(false)
  }

  const fetchEvaluations = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (searchQuery) params.set('q', searchQuery)
      if (selectedUser) params.set('user_id', selectedUser)
      const res = await fetch(`/api/admin/evaluations?${params}`, { headers })
      const data = await res.json()
      setEvaluations(data.evaluations || [])
    } catch (err) {
      console.error('Failed to fetch evaluations:', err)
    }
    setLoading(false)
  }

  const handleSyncDB = async () => {
    setSyncing(true)
    try {
      const res = await fetch('/api/admin/sync-db', { method: 'POST', headers })
      const data = await res.json()
      if (data.success) {
        alert('DB 동기화 완료!')
        fetchStats()
        fetchUsers()
        if (activeTab === 'evaluations') fetchEvaluations()
      } else {
        alert('동기화 실패: ' + data.message)
      }
    } catch (err) {
      alert('동기화 오류: ' + err.message)
    }
    setSyncing(false)
  }

  const handleSearch = (e) => {
    e.preventDefault()
    fetchEvaluations()
  }

  return (
    <div className="admin-overlay">
      <div className="admin-panel">
        <div className="admin-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '40px', height: '40px', borderRadius: '10px',
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'white', fontSize: '18px'
            }}>
              ⚙
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: '18px' }}>관리자 패널</h2>
              <span style={{ fontSize: '12px', color: '#888' }}>{user?.email}</span>
            </div>
          </div>
          <div className="admin-header-actions">
            <button className="sync-btn" onClick={handleSyncDB} disabled={syncing}>
              {syncing ? '⏳ 동기화 중...' : '☁️ S3 동기화'}
            </button>
            <button className="close-btn" onClick={onClose}>✕</button>
          </div>
        </div>

        <div className="admin-tabs">
          <button
            className={activeTab === 'dashboard' ? 'active' : ''}
            onClick={() => setActiveTab('dashboard')}
          >
            📊 대시보드
          </button>
          <button
            className={activeTab === 'users' ? 'active' : ''}
            onClick={() => setActiveTab('users')}
          >
            👥 사용자
          </button>
          <button
            className={activeTab === 'evaluations' ? 'active' : ''}
            onClick={() => setActiveTab('evaluations')}
          >
            📋 평가 데이터
          </button>
        </div>

        <div className="admin-content">
          {activeTab === 'dashboard' && (
            <div className="dashboard">
              <div className="stat-card" style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
                <div className="stat-icon">👥</div>
                <div className="stat-info">
                  <div className="stat-value">{stats.user_count}</div>
                  <div className="stat-label">총 사용자</div>
                </div>
              </div>
              <div className="stat-card" style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}>
                <div className="stat-icon">📝</div>
                <div className="stat-info">
                  <div className="stat-value">{stats.eval_count}</div>
                  <div className="stat-label">총 평가 수</div>
                </div>
              </div>
              <div className="stat-card" style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}>
                <div className="stat-icon">📈</div>
                <div className="stat-info">
                  <div className="stat-value">
                    {stats.user_count > 0 ? (stats.eval_count / stats.user_count).toFixed(1) : 0}
                  </div>
                  <div className="stat-label">인당 평균</div>
                </div>
              </div>

              <div className="recent-users">
                <h3>최근 가입 사용자</h3>
                {users.slice(0, 5).map((u) => (
                  <div key={u.id} className="recent-user-item">
                    {u.picture ? (
                      <img src={u.picture} alt="" className="user-avatar" />
                    ) : (
                      <div className="user-avatar-placeholder">👤</div>
                    )}
                    <div className="recent-user-info">
                      <span className="recent-user-name">{u.name}</span>
                      <span className="recent-user-email">{u.email}</span>
                    </div>
                    <span className="recent-user-date">
                      {new Date(u.created_at).toLocaleDateString('ko-KR')}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'users' && (
            <div className="users-table-container">
              {loading ? (
                <div className="loading">로딩 중...</div>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>이름</th>
                      <th>이메일</th>
                      <th>가입일</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td>
                          {u.picture && (
                            <img src={u.picture} alt="" className="user-avatar" />
                          )}
                          {u.name}
                        </td>
                        <td>{u.email}</td>
                        <td>{new Date(u.created_at).toLocaleString('ko-KR')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {activeTab === 'evaluations' && (
            <div className="evaluations-container">
              <form onSubmit={handleSearch} className="search-form">
                <input
                  type="text"
                  placeholder="검색 (비디오명, 파일명...)"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <select
                  value={selectedUser}
                  onChange={(e) => setSelectedUser(e.target.value)}
                >
                  <option value="">모든 사용자</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.name}</option>
                  ))}
                </select>
                <button type="submit">검색</button>
              </form>
              {loading ? (
                <div className="loading">로딩 중...</div>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>사용자</th>
                      <th>비디오</th>
                      <th>마스크 소스</th>
                      <th>파일</th>
                      <th>생성일</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluations.map((e) => (
                      <tr key={e.id}>
                        <td>{e.id}</td>
                        <td>{e.user_name}</td>
                        <td>{e.video_name}</td>
                        <td>{e.mask_source || '-'}</td>
                        <td>{e.filename}</td>
                        <td>{new Date(e.created_at).toLocaleString('ko-KR')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
