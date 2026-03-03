import { useEffect, useState } from 'react'

type ProjectSummary = {
  project_id: string
  mtime: number
  size: number
}

type ActiveProjectResponse = {
  remapper?: {
    active_project_id?: string
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init })
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}): ${await response.text()}`)
  }
  return (await response.json()) as T
}

export default function App() {
  const [status, setStatus] = useState('loading...')
  const [profileSourceUrl, setProfileSourceUrl] = useState('')
  const [remoteProjects, setRemoteProjects] = useState<ProjectSummary[]>([])
  const [activeProjectId, setActiveProjectId] = useState('')
  const [busyProjectId, setBusyProjectId] = useState('')

  async function loadAll(): Promise<void> {
    setStatus('refreshing profiles...')
    const [syncConfig, remote, active] = await Promise.all([
      request<{ profile_source_url: string }>('/api/sync/config'),
      request<{ projects: ProjectSummary[] }>('/api/sync/projects'),
      request<ActiveProjectResponse>('/api/cms/active_project'),
    ])
    setProfileSourceUrl(syncConfig.profile_source_url || '')
    setRemoteProjects((remote.projects ?? []).slice().sort((a, b) => b.mtime - a.mtime))
    setActiveProjectId(String(active.remapper?.active_project_id || '').trim())
    setStatus('ready')
  }

  async function activateProject(projectId: string): Promise<void> {
    try {
      setBusyProjectId(projectId)
      setStatus(`activating ${projectId}...`)
      await request(`/api/sync/projects/${encodeURIComponent(projectId)}/pull`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ apply: true }),
      })
      await loadAll()
      setStatus(`active profile: ${projectId}`)
    } finally {
      setBusyProjectId('')
    }
  }

  useEffect(() => {
    void loadAll().catch((error) => setStatus(String(error)))
  }, [])

  return (
    <main className="page">
      <section className="panel hero">
        <h1>Imperium Deck Client</h1>
        <p className="muted">Cloud profile selector for this Steam Deck.</p>
        <p className="muted mono">source: {profileSourceUrl || '-'}</p>
        <div className="row">
          <button onClick={() => void loadAll().catch((error) => setStatus(String(error)))}>Refresh</button>
          <span className="status mono">{status}</span>
        </div>
        <div className="activeBox">
          <span className="muted">Active Profile</span>
          <strong>{activeProjectId || '(none)'}</strong>
        </div>
      </section>

      <section className="panel">
        <h2>Profiles</h2>
        <div className="list">
          {remoteProjects.map((project) => {
            const isActive = project.project_id === activeProjectId
            const isBusy = busyProjectId === project.project_id
            return (
              <div key={project.project_id} className={`listRow ${isActive ? 'activeRow' : ''}`}>
                <div>
                  <strong>{project.project_id}</strong>
                  <div className="muted">Updated {new Date(project.mtime * 1000).toLocaleString()}</div>
                </div>
                <button
                  className={isActive ? 'primary' : ''}
                  disabled={isBusy}
                  onClick={() => void activateProject(project.project_id).catch((error) => setStatus(String(error)))}
                >
                  {isBusy ? 'Activating...' : isActive ? 'Active' : 'Set Active'}
                </button>
              </div>
            )
          })}
          {remoteProjects.length === 0 ? <p className="muted">No cloud profiles found.</p> : null}
        </div>
      </section>
    </main>
  )
}
