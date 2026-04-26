import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Link, Route, Routes, useParams } from 'react-router-dom'
import './styles.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`Request failed: ${res.status}`)
  return res.json()
}

function useFetch(path) {
  const [data, setData] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    let mounted = true
    setLoading(true)
    api(path)
      .then((json) => mounted && setData(json))
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoading(false))
    return () => {
      mounted = false
    }
  }, [path])

  return { data, loading, error, reload: () => api(path).then(setData) }
}

function Nav() {
  return (
    <nav>
      <Link to="/">Artworks</Link>
      <Link to="/review-queue">Review Queue</Link>
    </nav>
  )
}

function ArtworkTable({ rows }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Title</th><th>Artist</th><th>Source</th><th>Year</th><th>Medium</th><th>Quality</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.artwork_id}>
            <td><Link to={`/artworks/${a.artwork_id}`}>{a.artwork_title}</Link></td>
            <td>{a.artist_name}</td>
            <td>{a.source_name}</td>
            <td>{a.year_start || ''}{a.year_end ? `-${a.year_end}` : ''}</td>
            <td>{a.medium_text}</td>
            <td>{a.quality_score}</td>
            <td>{a.review_status || 'pending'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ArtworkListPage() {
  const { data, loading, error } = useFetch('/api/artworks')
  return <section><h2>Artwork List</h2>{loading ? 'Loading...' : error || <ArtworkTable rows={data} />}</section>
}

function ReviewQueuePage() {
  const { data, loading, error } = useFetch('/api/review-queue')
  return <section><h2>Review Queue</h2>{loading ? 'Loading...' : error || <ArtworkTable rows={data} />}</section>
}

function ArtworkDetailPage() {
  const { artworkId } = useParams()
  const [artwork, setArtwork] = React.useState(null)
  const [notes, setNotes] = React.useState('')
  const [loading, setLoading] = React.useState(true)

  const load = React.useCallback(() => {
    setLoading(true)
    api(`/api/artworks/${artworkId}`).then(setArtwork).finally(() => setLoading(false))
  }, [artworkId])

  React.useEffect(() => { load() }, [load])

  async function decide(type) {
    const body = { reviewer: 'admin', notes }
    if (type === 'reject') body.rejection_reason = notes || 'Rejected by admin'
    await api(`/api/artworks/${artworkId}/${type}`, { method: 'POST', body: JSON.stringify(body) })
    await load()
  }

  if (loading) return <p>Loading...</p>
  if (!artwork) return <p>Not found.</p>

  return (
    <section>
      <h2>{artwork.artwork_title}</h2>
      {artwork.image_url && <img src={artwork.image_url} alt={artwork.artwork_title} />}
      <ul>
        <li><strong>Artist:</strong> {artwork.artist_name}</li>
        <li><strong>Source:</strong> {artwork.source_name} — <a href={artwork.source_url} target="_blank">{artwork.source_url}</a></li>
        <li><strong>Medium:</strong> {artwork.medium_text}</li>
        <li><strong>Year:</strong> {artwork.year_start} / {artwork.year_end}</li>
        <li><strong>Quality:</strong> {artwork.quality_score}</li>
        <li><strong>Review status:</strong> {artwork.review_status || 'pending'}</li>
      </ul>
      <div className="controls">
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Review notes or rejection reason" />
        <button onClick={() => decide('approve')}>Approve</button>
        <button onClick={() => decide('reject')}>Reject</button>
      </div>
    </section>
  )
}

function App() {
  return (
    <div className="app">
      <h1>Artio Admin</h1>
      <Nav />
      <Routes>
        <Route path="/" element={<ArtworkListPage />} />
        <Route path="/review-queue" element={<ReviewQueuePage />} />
        <Route path="/artworks/:artworkId" element={<ArtworkDetailPage />} />
      </Routes>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
