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
  }, [])

  useEffect(() => {
    if (activeTab === 'users') fetchUsers()
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
        if (activeTab === 'users') fetchUsers()
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
          <h2>관리자 패널</h2>
          <div className="admin-header-actions">
            <button className="sync-btn" onClick={handleSyncDB} disabled={syncing}>
              {syncing ? '동기화 중...' : 'S3 동기화'}
            </button>
            <button className="close-btn" onClick={onClose}>×</button>
          </div>
        </div>

        <div className="admin-tabs">
          <button
            className={activeTab === 'dashboard' ? 'active' : ''}
            onClick={() => setActiveTab('dashboard')}
          >
            대시보드
          </button>
          <button
            className={activeTab === 'users' ? 'active' : ''}
            onClick={() => setActiveTab('users')}
          >
            사용자
          </button>
          <button
            className={activeTab === 'evaluations' ? 'active' : ''}
            onClick={() => setActiveTab('evaluations')}
          >
            평가 데이터
          </button>
        </div>

        <div className="admin-content">
          {activeTab === 'dashboard' && (
            <div className="dashboard">
              <div className="stat-card">
                <div className="stat-value">{stats.user_count}</div>
                <div className="stat-label">총 사용자</div>
              </div>
              <div className="stat-card">
                <div className="stat-value">{stats.eval_count}</div>
                <div className="stat-label">총 평가 수</div>
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
