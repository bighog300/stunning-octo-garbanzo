import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Link, Route, Routes, useParams, useSearchParams } from 'react-router-dom'
import './styles.css'

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`Request failed: ${res.status}`)
  return res.json()
}

function getArtists({ search = '', limit = 100, offset = 0 } = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })

  if (search?.trim()) {
    params.set('search', search.trim())
  }

  return api(`/api/artists?${params.toString()}`)
}

function getArtistProfile(artistName) {
  return api(`/api/artists/${encodeURIComponent(artistName)}`)
}

function saveArtistBio(artistName, payload) {
  return api(`/api/artists/${encodeURIComponent(artistName)}/bio`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function getModerationSummary() {
  return api('/api/moderation/queues')
}

function getModerationQueue(queueName, { limit = 100, offset = 0 } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return api(`/api/moderation/queue/${encodeURIComponent(queueName)}?${params.toString()}`)
}

function createDataQualityFlag(payload) {
  return api('/api/moderation/flags', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function useFetch(path) {
  const [data, setData] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    let mounted = true
    setLoading(true)
    setError('')
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
      <Link to="/artists">Artists</Link>
      <Link to="/moderation">Moderation</Link>
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

function ArtistListPage() {
  const [search, setSearch] = React.useState('')
  const [artists, setArtists] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    let mounted = true
    setLoading(true)
    setError('')

    getArtists({ search, limit: 100, offset: 0 })
      .then((json) => {
        if (!mounted) return
        setArtists(Array.isArray(json) ? json : [])
      })
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoading(false))

    return () => {
      mounted = false
    }
  }, [search])

  return (
    <section>
      <h2>Artists</h2>
      <label className="field-label" htmlFor="artist-search">Search artists</label>
      <input
        id="artist-search"
        type="search"
        className="search-input"
        placeholder="Search by artist name"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {loading && <p>Loading artists...</p>}
      {!loading && error && <p className="error-text">Failed to load artists: {error}</p>}
      {!loading && !error && artists.length === 0 && <p>No artists found.</p>}

      {!loading && !error && artists.length > 0 && (
        <div className="artist-grid">
          {artists.map((artist, idx) => {
            const artistName = artist.artist_name || 'Unknown artist'
            const bioText = artist.artist_bio || 'No bio available'
            const bioPreview = bioText.length > 200 ? `${bioText.slice(0, 200)}...` : bioText
            return (
              <article className="artist-card" key={`${artistName}-${idx}`}>
                <h3>{artistName}</h3>
                <p><strong>Artworks:</strong> {artist.artwork_count ?? 0}</p>
                <p><strong>Source:</strong> {artist.source_domain || 'Unknown'}</p>
                <p>{bioPreview}</p>
                {artist.last_seen && <p><strong>Last seen:</strong> {artist.last_seen}</p>}
                <Link to={`/artists/${encodeURIComponent(artistName)}`}>View artist profile</Link>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function ArtistProfilePage() {
  const { artistName = '' } = useParams()
  const [profile, setProfile] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [editedBio, setEditedBio] = React.useState('')
  const [saveStatus, setSaveStatus] = React.useState('')
  const [isSaving, setIsSaving] = React.useState(false)

  const loadProfile = React.useCallback(() => {
    let mounted = true
    setLoading(true)
    setError('')
    setSaveStatus('')

    getArtistProfile(artistName)
      .then((json) => {
        if (!mounted) return
        setProfile(json)
        setEditedBio(json?.artist?.artist_bio || '')
      })
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoading(false))

    return () => {
      mounted = false
    }
  }, [artistName])

  React.useEffect(() => loadProfile(), [loadProfile])

  if (loading) return <section><h2>Artist Profile</h2><p>Loading artist profile...</p></section>
  if (error) return <section><h2>Artist Profile</h2><p className="error-text">Failed to load artist profile: {error}</p></section>
  if (!profile || !profile.artist) return <section><h2>Artist Profile</h2><p>Artist not found.</p></section>

  const { artist, artworks = [], events = [] } = profile
  const displayName = artist.artist_name || artistName
  const currentBio = artist.artist_bio || ''
  const hasEditedBio = Boolean(artist.edited_artist_bio)

  async function onSaveBio() {
    setIsSaving(true)
    setSaveStatus('')
    try {
      await saveArtistBio(displayName, {
        edited_bio: editedBio,
        edited_by: 'admin',
        edit_notes: 'Manual edit from artist profile page',
        source_domain: artist.source_domain || 'art.co.za',
      })
      setSaveStatus('Bio saved successfully.')
      loadProfile()
    } catch (err) {
      setSaveStatus(`Failed to save bio: ${err.message}`)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section>
      <h2>{displayName}</h2>
      <p><strong>Artwork count:</strong> {artist.artwork_count ?? artworks.length ?? 0}</p>
      {artist.original_artist_bio && (
        <p>
          <strong>Original bio:</strong> {artist.original_artist_bio}
        </p>
      )}
      <p><strong>Current bio:</strong> {currentBio || 'No bio available'}</p>
      {hasEditedBio && artist.bio_last_edited_at && (
        <p>
          <strong>Last edited:</strong> {artist.bio_last_edited_at}
          {artist.bio_edited_by ? ` by ${artist.bio_edited_by}` : ''}
        </p>
      )}
      <div className="controls">
        <label className="field-label" htmlFor="artist-bio-edit">Edit bio</label>
        <textarea
          id="artist-bio-edit"
          value={editedBio}
          onChange={(e) => setEditedBio(e.target.value)}
          placeholder="Write a curated artist bio"
        />
        <button onClick={onSaveBio} disabled={isSaving}>
          {isSaving ? 'Saving...' : 'Save bio edit'}
        </button>
        {saveStatus && <p className={saveStatus.startsWith('Failed') ? 'error-text' : ''}>{saveStatus}</p>}
      </div>
      {artist.source_url && (
        <p>
          <strong>Profile:</strong>{' '}
          <a href={artist.source_url} target="_blank" rel="noreferrer">{artist.source_url}</a>
        </p>
      )}

      <h3>Artworks</h3>
      {artworks.length === 0 && <p>No artworks found.</p>}
      {artworks.length > 0 && (
        <div className="artwork-grid">
          {artworks.map((work, idx) => {
            const title = work.artwork_title || work.title || 'Untitled'
            const imageUrl = work.image_url || work.thumbnail_url
            return (
              <article className="artwork-card" key={`${work.artwork_id || title}-${idx}`}>
                {imageUrl ? <img src={imageUrl} alt={title} /> : <div className="image-fallback">No image</div>}
                <h4>{title}</h4>
                {work.medium_text && <p>{work.medium_text}</p>}
                {(work.year_start || work.year_end) && (
                  <p>
                    {work.year_start || ''}
                    {work.year_end ? `-${work.year_end}` : ''}
                  </p>
                )}
                {work.review_status && <p><strong>Status:</strong> {work.review_status}</p>}
                {work.artwork_id && <Link to={`/artworks/${work.artwork_id}`}>View artwork</Link>}
              </article>
            )
          })}
        </div>
      )}

      <h3>Events</h3>
      {events.length === 0 && <p>No events linked yet.</p>}
      {events.length > 0 && (
        <div className="event-list">
          {events.map((event, idx) => (
            <article className="event-card" key={`${event.event_id || event.title || event.event_title}-${idx}`}>
              <h4>{event.event_title || event.title || 'Untitled event'}</h4>
              {(event.start_date || event.end_date) && (
                <p>
                  {event.start_date || 'Unknown start'}
                  {event.end_date ? ` → ${event.end_date}` : ''}
                </p>
              )}
              <p>
                {event.venue_name || 'Unknown venue'}
                {(event.city || event.country) && ` — ${[event.city, event.country].filter(Boolean).join(', ')}`}
              </p>
              {event.source_url && (
                <a href={event.source_url} target="_blank" rel="noreferrer">Event source</a>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
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

const MODERATION_QUEUE_CONFIG = {
  'artworks-pending-review': { title: 'Pending artwork review', summaryKey: 'artworks_pending_review', issueType: 'pending_review', type: 'artwork' },
  'artists-missing-bio': { title: 'Missing bios', summaryKey: 'artists_missing_bio', issueType: 'missing_bio', type: 'artist' },
  'artists-short-bio': { title: 'Short bios', summaryKey: 'artists_short_bio', issueType: 'short_bio', type: 'artist' },
  'artists-suspect-name': { title: 'Suspect artist names', summaryKey: 'artists_suspect_name', issueType: 'suspect_artist_name', type: 'artist' },
  'artists-with-manual-bio': { title: 'Manual bio overrides', summaryKey: 'artists_with_manual_bio', issueType: 'manual_bio_override', type: 'artist' },
  'artists-without-events': { title: 'Artists without events', summaryKey: 'artists_without_events', issueType: 'missing_events', type: 'artist' },
  'broken-or-missing-images': { title: 'Broken/missing images', summaryKey: 'broken_or_missing_images', issueType: 'broken_or_missing_image', type: 'artwork' },
}

function ModerationFlagForm({ item, queueName }) {
  const [isOpen, setIsOpen] = React.useState(false)
  const [notes, setNotes] = React.useState('')
  const [status, setStatus] = React.useState('')
  const [isSaving, setIsSaving] = React.useState(false)

  async function submitFlag() {
    setIsSaving(true)
    setStatus('')
    try {
      const config = MODERATION_QUEUE_CONFIG[queueName]
      await createDataQualityFlag({
        entity_type: config?.type || 'artist',
        entity_id: item.artwork_id || null,
        artist_name: item.artist_name || null,
        issue_type: config?.issueType || 'data_quality_issue',
        notes: notes.trim() || null,
        created_by: 'admin',
      })
      setStatus('Flag submitted.')
      setNotes('')
    } catch (err) {
      setStatus(`Failed to submit flag: ${err.message}`)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="flag-form">
      <button onClick={() => setIsOpen((v) => !v)}>{isOpen ? 'Close flag form' : 'Flag issue'}</button>
      {isOpen && (
        <>
          <textarea
            placeholder="Describe the issue"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <button onClick={submitFlag} disabled={isSaving}>{isSaving ? 'Submitting...' : 'Submit flag'}</button>
          {status && <p className={status.startsWith('Failed') ? 'error-text' : ''}>{status}</p>}
        </>
      )}
    </div>
  )
}

function ModerationQueueList({ queueName, items }) {
  const config = MODERATION_QUEUE_CONFIG[queueName]
  if (!config) return <p className="error-text">Unknown queue.</p>
  if (items.length === 0) return <p>No records in this queue.</p>

  return (
    <div className="queue-list">
      {items.map((item, idx) => (
        <article className="queue-item" key={`${item.artwork_id || item.artist_name || idx}-${idx}`}>
          <p><span className="issue-badge">{item.issue_reason || config.issueType}</span></p>
          {config.type === 'artist' ? (
            <>
              <h3><Link to={`/artists/${encodeURIComponent(item.artist_name)}`}>{item.artist_name || 'Unknown artist'}</Link></h3>
              <p><strong>Artworks:</strong> {item.artwork_count ?? 0}</p>
              <p>{item.artist_bio ? `${item.artist_bio.slice(0, 220)}${item.artist_bio.length > 220 ? '...' : ''}` : 'No bio available'}</p>
              {item.edited_bio && <p><strong>Manual bio set.</strong> {item.edited_by ? `By ${item.edited_by}` : ''} {item.edited_at || ''}</p>}
              {item.profile_url && <p><a href={item.profile_url} target="_blank" rel="noreferrer">Profile source</a></p>}
              <p><Link to={`/artists/${encodeURIComponent(item.artist_name)}`}>Open artist</Link></p>
            </>
          ) : (
            <>
              {item.image_url ? <img src={item.image_url} alt={item.artwork_title || 'Artwork'} /> : <div className="image-fallback">No image</div>}
              <h3>{item.artwork_title || 'Untitled artwork'}</h3>
              <p><strong>Artist:</strong> <Link to={`/artists/${encodeURIComponent(item.artist_name || '')}`}>{item.artist_name || 'Unknown artist'}</Link></p>
              <p><strong>Status:</strong> {item.review_status || 'pending'}</p>
              {item.source_url && <p><a href={item.source_url} target="_blank" rel="noreferrer">Source URL</a></p>}
              {item.artwork_id && <p><Link to={`/artworks/${item.artwork_id}`}>Open artwork</Link></p>}
            </>
          )}
          <ModerationFlagForm item={item} queueName={queueName} />
        </article>
      ))}
    </div>
  )
}

function ModerationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [summary, setSummary] = React.useState({})
  const [records, setRecords] = React.useState([])
  const [loadingSummary, setLoadingSummary] = React.useState(true)
  const [loadingQueue, setLoadingQueue] = React.useState(false)
  const [error, setError] = React.useState('')
  const selectedQueue = searchParams.get('queue') || ''

  React.useEffect(() => {
    let mounted = true
    setLoadingSummary(true)
    getModerationSummary()
      .then((json) => mounted && setSummary(json || {}))
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoadingSummary(false))
    return () => { mounted = false }
  }, [])

  React.useEffect(() => {
    if (!selectedQueue) {
      setRecords([])
      return
    }
    let mounted = true
    setLoadingQueue(true)
    setError('')
    getModerationQueue(selectedQueue, { limit: 100, offset: 0 })
      .then((json) => mounted && setRecords(Array.isArray(json) ? json : []))
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoadingQueue(false))
    return () => { mounted = false }
  }, [selectedQueue])

  return (
    <section>
      <h2>Moderation</h2>
      {loadingSummary && <p>Loading moderation queues...</p>}
      {error && <p className="error-text">Failed to load moderation data: {error}</p>}
      <div className="moderation-grid">
        {Object.entries(MODERATION_QUEUE_CONFIG).map(([queueName, config]) => (
          <article className="moderation-card" key={queueName}>
            <h3>{config.title}</h3>
            <p>{summary?.[config.summaryKey] ?? 0}</p>
            <button onClick={() => setSearchParams({ queue: queueName })}>Open queue</button>
          </article>
        ))}
      </div>
      {selectedQueue && (
        <>
          <h3>{MODERATION_QUEUE_CONFIG[selectedQueue]?.title || selectedQueue}</h3>
          {loadingQueue ? <p>Loading queue records...</p> : <ModerationQueueList queueName={selectedQueue} items={records} />}
        </>
      )}
    </section>
  )
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
        <li><strong>Source:</strong> {artwork.source_name} — <a href={artwork.source_url} target="_blank" rel="noreferrer">{artwork.source_url}</a></li>
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
        <Route path="/artists" element={<ArtistListPage />} />
        <Route path="/artists/:artistName" element={<ArtistProfilePage />} />
        <Route path="/moderation" element={<ModerationPage />} />
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
