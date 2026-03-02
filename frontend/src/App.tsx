import { useEffect, useMemo, useRef, useState } from 'react'

type Device = {
  path: string
  name: string
  uniq?: string
  capabilities?: string[]
}

type ProjectSummary = {
  project_id: string
  mtime: number
  size: number
}

type EventMessage = {
  timestamp?: number
  device_name?: string
  device_path?: string
  event_type_name?: string
  code_name?: string
  code?: string
  value?: number
  decoded?: Record<string, number>
}

type DeviceState = {
  buttons: Record<string, number>
  axes: Record<string, number>
}

const LABELS: Record<string, string> = {
  A: 'A Button',
  B: 'B Button',
  X: 'X Button',
  Y: 'Y Button',
  L1: 'Left Shoulder (L1)',
  R1: 'Right Shoulder (R1)',
  L2_BTN: 'Left Trigger Button (L2)',
  R2_BTN: 'Right Trigger Button (R2)',
  L2: 'Left Trigger (L2)',
  R2: 'Right Trigger (R2)',
  L3: 'Left Stick Click (L3)',
  R3: 'Right Stick Click (R3)',
  DPAD_UP: 'D-Pad Up',
  DPAD_RIGHT: 'D-Pad Right',
  DPAD_DOWN: 'D-Pad Down',
  DPAD_LEFT: 'D-Pad Left',
  MENU: 'Menu',
  STEAM: 'Steam',
  QAM: 'Quick Access',
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init })
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}): ${await response.text()}`)
  }
  return (await response.json()) as T
}

function prettyLabel(value: string): string {
  return LABELS[value] ?? value
}

function fmtTime(ts?: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleTimeString()
}

export default function App() {
  const [status, setStatus] = useState('ready')
  const [devices, setDevices] = useState<Device[]>([])
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set())

  const [remoteProjects, setRemoteProjects] = useState<ProjectSummary[]>([])
  const [localProjects, setLocalProjects] = useState<ProjectSummary[]>([])
  const [profileSourceUrl, setProfileSourceUrl] = useState('')

  const [events, setEvents] = useState<EventMessage[]>([])
  const [liveState, setLiveState] = useState<Record<string, DeviceState>>({})
  const pingRef = useRef<number | null>(null)

  async function loadDevices(): Promise<void> {
    const out = await request<{ devices: Device[]; default: string[] }>('/api/devices')
    setDevices(out.devices ?? [])
    setSelectedPaths(new Set(out.default ?? []))
  }

  async function loadProjects(): Promise<void> {
    const [syncConfig, remote, local] = await Promise.all([
      request<{ profile_source_url: string }>('/api/sync/config'),
      request<{ projects: ProjectSummary[] }>('/api/sync/projects'),
      request<{ projects: ProjectSummary[] }>('/api/cms/projects'),
    ])
    setProfileSourceUrl(syncConfig.profile_source_url || '')
    setRemoteProjects(remote.projects ?? [])
    setLocalProjects(local.projects ?? [])
  }

  async function postStart(paths: string[]): Promise<void> {
    await request('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_paths: paths }),
    })
  }

  async function stopReader(): Promise<void> {
    await request('/api/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
  }

  async function applyLocalProject(projectId: string): Promise<void> {
    setStatus(`applying ${projectId}...`)
    await request(`/api/cms/projects/${encodeURIComponent(projectId)}/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    setStatus(`applied ${projectId}`)
  }

  async function pullFromCloud(projectId: string): Promise<void> {
    setStatus(`pulling ${projectId} from cloud...`)
    await request(`/api/sync/projects/${encodeURIComponent(projectId)}/pull`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply: true }),
    })
    await loadProjects()
    setStatus(`pulled + applied ${projectId}`)
  }

  function connectWs(): () => void {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/events`)

    ws.onopen = () => {
      setStatus('ws connected')
      pingRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 15000)
    }

    ws.onmessage = (message) => {
      try {
        const payload = JSON.parse(message.data) as EventMessage
        setEvents((prev) => {
          const next = [...prev, payload]
          if (next.length > 500) next.shift()
          return next
        })

        const key = payload.device_path || 'unknown'
        setLiveState((prev) => {
          const current = prev[key] ?? { buttons: {}, axes: {} }
          const next: DeviceState = {
            buttons: { ...current.buttons },
            axes: { ...current.axes },
          }
          if (payload.event_type_name === 'EV_KEY' && payload.code_name) {
            next.buttons[payload.code_name] = Number(payload.value || 0)
          } else if (payload.event_type_name === 'EV_ABS' && payload.code_name) {
            next.axes[payload.code_name] = Number(payload.value || 0)
          } else if (payload.event_type_name === 'HIDRAW' && payload.decoded) {
            for (const [name, value] of Object.entries(payload.decoded)) {
              if (name.endsWith('_X') || name.endsWith('_Y')) next.axes[name] = value
              else next.buttons[name] = value
            }
          }
          return { ...prev, [key]: next }
        })
      } catch {
        setStatus('ws parse error')
      }
    }

    ws.onclose = () => {
      setStatus('ws disconnected, retrying...')
      window.setTimeout(() => connectWs(), 1200)
    }

    ws.onerror = () => setStatus('ws error')

    return () => {
      if (pingRef.current !== null) window.clearInterval(pingRef.current)
      ws.close()
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([loadDevices(), loadProjects()])
        setStatus('ready')
      } catch (error) {
        setStatus(String(error))
      }
    })()
    const cleanup = connectWs()
    return cleanup
  }, [])

  const deviceCards = useMemo(
    () =>
      devices.map((device) => {
        const checked = selectedPaths.has(device.path)
        return (
          <article key={device.path} className="card">
            <label className="checkboxRow">
              <input
                type="checkbox"
                checked={checked}
                onChange={() => {
                  setSelectedPaths((prev) => {
                    const next = new Set(prev)
                    if (next.has(device.path)) next.delete(device.path)
                    else next.add(device.path)
                    return next
                  })
                }}
              />
              <span>{device.name || 'unknown'}</span>
            </label>
            <div className="mono">{device.path}</div>
            <div className="mono">uniq: {device.uniq || '-'}</div>
            <div className="chips">
              {(device.capabilities || []).slice(0, 8).map((cap) => (
                <span key={cap} className="chip">{cap}</span>
              ))}
            </div>
          </article>
        )
      }),
    [devices, selectedPaths],
  )

  const recentEvents = [...events].slice(-100).reverse()

  return (
    <main className="page">
      <section className="panel hero">
        <h1>Imperium Deck Client</h1>
        <p className="muted">Local runtime on Steam Deck with cloud profile pull.</p>
        <div className="row">
          <button onClick={() => void loadDevices().catch((e) => setStatus(String(e)))}>Refresh Devices</button>
          <button onClick={() => void postStart([...selectedPaths]).then(() => setStatus('started selected devices')).catch((e) => setStatus(String(e)))}>Start Selected</button>
          <button onClick={() => void postStart([]).then(() => setStatus('started default devices')).catch((e) => setStatus(String(e)))}>Start Default</button>
          <button className="danger" onClick={() => void stopReader().then(() => setStatus('reader stopped')).catch((e) => setStatus(String(e)))}>Stop</button>
          <span className="status mono">{status}</span>
        </div>
      </section>

      <section className="panel">
        <h2>Cloud Profiles</h2>
        <p className="muted mono">source: {profileSourceUrl || '-'}</p>
        <div className="list">
          {remoteProjects.map((project) => (
            <div key={project.project_id} className="listRow">
              <div>
                <strong>{project.project_id}</strong>
                <div className="muted">Updated {new Date(project.mtime * 1000).toLocaleString()}</div>
              </div>
              <button className="primary" onClick={() => void pullFromCloud(project.project_id).catch((e) => setStatus(String(e)))}>
                Pull + Apply
              </button>
            </div>
          ))}
          {remoteProjects.length === 0 ? <p className="muted">No cloud profiles found.</p> : null}
        </div>
      </section>

      <section className="panel">
        <div className="row spread">
          <h2>Local Profiles</h2>
          <button onClick={() => void loadProjects().catch((e) => setStatus(String(e)))}>Refresh Profiles</button>
        </div>
        <div className="list">
          {localProjects.map((project) => (
            <div key={project.project_id} className="listRow">
              <div>
                <strong>{project.project_id}</strong>
                <div className="muted">{Math.round(project.size / 1024)} KB</div>
              </div>
              <button onClick={() => void applyLocalProject(project.project_id).catch((e) => setStatus(String(e)))}>Apply</button>
            </div>
          ))}
          {localProjects.length === 0 ? <p className="muted">No local profiles yet.</p> : null}
        </div>
      </section>

      <section className="panel">
        <h2>Devices</h2>
        <div className="grid">{deviceCards}</div>
      </section>

      <section className="panel">
        <h2>Recent Events</h2>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>time</th>
                <th>device</th>
                <th>type</th>
                <th>code</th>
                <th>value</th>
              </tr>
            </thead>
            <tbody>
              {recentEvents.map((event, idx) => (
                <tr key={`${event.timestamp}-${idx}`}>
                  <td>{fmtTime(event.timestamp)}</td>
                  <td className="mono">{(event.device_name || '').slice(0, 28)}</td>
                  <td>{event.event_type_name || ''}</td>
                  <td className="mono">{prettyLabel(String(event.code_name || event.code || ''))}</td>
                  <td className="mono">{String(event.value ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>Live State</h2>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>device</th>
                <th>buttons</th>
                <th>axes</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(liveState).map(([device, value]) => {
                const buttons = Object.entries(value.buttons)
                  .filter(([, v]) => v !== 0)
                  .map(([name, v]) => `${prettyLabel(name)}:${v}`)
                  .join(' ')
                const axes = Object.entries(value.axes)
                  .filter(([, v]) => v !== 0)
                  .map(([name, v]) => `${prettyLabel(name)}:${v}`)
                  .join(' ')
                return (
                  <tr key={device}>
                    <td className="mono">{device}</td>
                    <td className="mono">{buttons || '-'}</td>
                    <td className="mono">{axes || '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  )
}
