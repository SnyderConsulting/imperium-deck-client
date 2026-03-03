import { useEffect, useRef, useState } from 'react'

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
  const [focusedIndex, setFocusedIndex] = useState(0)
  const [gamepadConnected, setGamepadConnected] = useState(false)
  const lastMoveAtRef = useRef(0)
  const wasAPressedRef = useRef(false)
  const wasBPressedRef = useRef(false)

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

  useEffect(() => {
    if (remoteProjects.length === 0) {
      setFocusedIndex(0)
      return
    }

    const activeIndex = remoteProjects.findIndex((project) => project.project_id === activeProjectId)
    if (activeIndex >= 0) {
      setFocusedIndex(activeIndex)
      return
    }

    setFocusedIndex((current) => Math.max(0, Math.min(current, remoteProjects.length - 1)))
  }, [remoteProjects, activeProjectId])

  useEffect(() => {
    let rafId = 0

    const loop = (): void => {
      const gamepads = navigator.getGamepads ? Array.from(navigator.getGamepads()).filter(Boolean) : []
      const gamepad = (gamepads[0] ?? null) as Gamepad | null
      const connected = Boolean(gamepad)
      if (connected !== gamepadConnected) {
        setGamepadConnected(connected)
      }

      if (gamepad && remoteProjects.length > 0) {
        const now = Date.now()
        const upPressed = Boolean(gamepad.buttons[12]?.pressed) || gamepad.axes[1] < -0.6
        const downPressed = Boolean(gamepad.buttons[13]?.pressed) || gamepad.axes[1] > 0.6
        const aPressed = Boolean(gamepad.buttons[0]?.pressed)
        const bPressed = Boolean(gamepad.buttons[1]?.pressed)

        if ((upPressed || downPressed) && now - lastMoveAtRef.current > 180) {
          setFocusedIndex((current) => {
            if (upPressed && !downPressed) {
              return current <= 0 ? remoteProjects.length - 1 : current - 1
            }
            if (downPressed && !upPressed) {
              return (current + 1) % remoteProjects.length
            }
            return current
          })
          lastMoveAtRef.current = now
        }

        if (aPressed && !wasAPressedRef.current) {
          const project = remoteProjects[focusedIndex]
          if (project && busyProjectId === '') {
            void activateProject(project.project_id).catch((error) => setStatus(String(error)))
          }
        }

        if (bPressed && !wasBPressedRef.current) {
          void loadAll().catch((error) => setStatus(String(error)))
        }

        wasAPressedRef.current = aPressed
        wasBPressedRef.current = bPressed
      } else {
        wasAPressedRef.current = false
        wasBPressedRef.current = false
      }

      rafId = window.requestAnimationFrame(loop)
    }

    rafId = window.requestAnimationFrame(loop)
    return () => window.cancelAnimationFrame(rafId)
  }, [focusedIndex, busyProjectId, gamepadConnected, remoteProjects])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (remoteProjects.length === 0) {
        return
      }

      const key = event.key.toLowerCase()
      if (key === 'arrowup' || key === 'w') {
        event.preventDefault()
        setFocusedIndex((current) => (current <= 0 ? remoteProjects.length - 1 : current - 1))
        return
      }

      if (key === 'arrowdown' || key === 's') {
        event.preventDefault()
        setFocusedIndex((current) => (current + 1) % remoteProjects.length)
        return
      }

      if (key === 'enter' || key === ' ') {
        event.preventDefault()
        const project = remoteProjects[focusedIndex]
        if (project && busyProjectId === '') {
          void activateProject(project.project_id).catch((error) => setStatus(String(error)))
        }
        return
      }

      if (key === 'escape' || key === 'backspace' || key === 'b' || key === 'r') {
        event.preventDefault()
        void loadAll().catch((error) => setStatus(String(error)))
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [busyProjectId, focusedIndex, remoteProjects])

  return (
    <main className="page">
      <section className="panel hero">
        <h1>Imperium Deck Client</h1>
        <p className="muted">Cloud profile selector for this Steam Deck.</p>
        <p className="muted mono">source: {profileSourceUrl || '-'}</p>
        <p className="muted">
          {gamepadConnected
            ? 'Controls: D-pad = move, A = set active, B = refresh.'
            : 'Controls: Arrow Up/Down (or W/S), Enter = set active, B/Esc/R = refresh.'}
        </p>
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
            const isFocused = remoteProjects[focusedIndex]?.project_id === project.project_id
            return (
              <div
                key={project.project_id}
                className={`listRow ${isActive ? 'activeRow' : ''} ${isFocused ? 'focusedRow' : ''}`}
                onClick={() => setFocusedIndex(remoteProjects.findIndex((entry) => entry.project_id === project.project_id))}
              >
                <div>
                  <strong>{project.project_id}</strong>
                  <div className="muted">Updated {new Date(project.mtime * 1000).toLocaleString()}</div>
                </div>
                <button
                  className={isActive ? 'primary' : ''}
                  disabled={isBusy}
                  onFocus={() => setFocusedIndex(remoteProjects.findIndex((entry) => entry.project_id === project.project_id))}
                  onClick={() => void activateProject(project.project_id).catch((error) => setStatus(String(error)))}
                >
                  {isBusy ? 'Activating...' : isActive ? 'Active' : isFocused ? 'Set Active (A)' : 'Set Active'}
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
