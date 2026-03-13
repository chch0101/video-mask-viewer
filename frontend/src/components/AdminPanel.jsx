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

  const headers = { 'Authorization': `Bearer ${user?.credential || ''}` }

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
          <div className="admin-title">
            <h2>Admin</h2>
            <span className="admin-email">{user?.email}</span>
          </div>
          <div className="admin-header-actions">
            <button className="sync-btn" onClick={handleSyncDB} disabled={syncing}>
              {syncing ? 'Syncing...' : 'Sync from S3'}
            </button>
            <button className="close-btn" onClick={onClose}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>

        <div className="admin-tabs">
          <button
            className={activeTab === 'dashboard' ? 'active' : ''}
            onClick={() => setActiveTab('dashboard')}
          >
            Dashboard
          </button>
          <button
            className={activeTab === 'users' ? 'active' : ''}
            onClick={() => setActiveTab('users')}
          >
            Users
          </button>
          <button
            className={activeTab === 'evaluations' ? 'active' : ''}
            onClick={() => setActiveTab('evaluations')}
          >
            Evaluations
          </button>
        </div>

        <div className="admin-content">
          {activeTab === 'dashboard' && (
            <div className="dashboard">
              <div className="stats-grid">
                <div className="stat-card">
                  <div className="stat-value">{stats.user_count}</div>
                  <div className="stat-label">Total Users</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">{stats.eval_count}</div>
                  <div className="stat-label">Total Evaluations</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">
                    {stats.user_count > 0 ? (stats.eval_count / stats.user_count).toFixed(1) : '0'}
                  </div>
                  <div className="stat-label">Avg per User</div>
                </div>
              </div>

              <div className="recent-section">
                <h3>Recent Users</h3>
                <div className="recent-list">
                  {users.slice(0, 5).map((u) => (
                    <div key={u.id} className="recent-item">
                      <div className="recent-item-avatar">
                        {u.picture ? (
                          <img src={u.picture} alt="" />
                        ) : (
                          <div className="avatar-placeholder">{u.name?.charAt(0) || '?'}</div>
                        )}
                      </div>
                      <div className="recent-item-info">
                        <span className="recent-item-name">{u.name}</span>
                        <span className="recent-item-sub">{u.email}</span>
                      </div>
                      <span className="recent-item-date">
                        {new Date(u.created_at).toLocaleDateString('ko-KR')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'users' && (
            <div className="table-container">
              {loading ? (
                <div className="loading">Loading...</div>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Email</th>
                      <th>Joined</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td className="user-cell">
                          {u.picture ? (
                            <img src={u.picture} alt="" className="table-avatar" />
                          ) : (
                            <div className="table-avatar-placeholder">{u.name?.charAt(0) || '?'}</div>
                          )}
                          <span>{u.name}</span>
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
                  placeholder="Search video, filename..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                <select
                  value={selectedUser}
                  onChange={(e) => setSelectedUser(e.target.value)}
                >
                  <option value="">All users</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.name}</option>
                  ))}
                </select>
                <button type="submit">Search</button>
              </form>
              {loading ? (
                <div className="loading">Loading...</div>
              ) : (
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>User</th>
                      <th>Video</th>
                      <th>Mask Source</th>
                      <th>File</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluations.map((e) => (
                      <tr key={e.id}>
                        <td>{e.id}</td>
                        <td>{e.user_name}</td>
                        <td>{e.video_name}</td>
                        <td><span className="tag">{e.mask_source || '-'}</span></td>
                        <td className="filename">{e.filename}</td>
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
