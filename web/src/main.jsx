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

function getArtists({ search = '', limit = 100, offset = 0, includeHidden = false } = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })

  if (search?.trim()) {
    params.set('search', search.trim())
  }
  if (includeHidden) params.set('include_hidden', 'true')

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

function getModerationQueue(queueName, { limit = 100, offset = 0, status = 'open' } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), status })
  return api(`/api/moderation/queue/${encodeURIComponent(queueName)}?${params.toString()}`)
}

function createDataQualityFlag(payload) {
  return api('/api/moderation/flags', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function getModerationFlags(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  return api(`/api/moderation/flags?${search.toString()}`)
}

function resolveModerationFlag(flagId, payload) {
  return api(`/api/moderation/flags/${encodeURIComponent(flagId)}/resolve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function reopenModerationFlag(flagId, payload) {
  return api(`/api/moderation/flags/${encodeURIComponent(flagId)}/reopen`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function updateArtistModeration(artistName, payload) {
  return api(`/api/artists/${encodeURIComponent(artistName)}/moderation`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function approveArtwork(artworkId, payload) {
  return api(`/api/artworks/${encodeURIComponent(artworkId)}/approve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function rejectArtwork(artworkId, payload) {
  return api(`/api/artworks/${encodeURIComponent(artworkId)}/reject`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function getAdminEvents(filters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    params.set(key, String(value))
  })
  return api(`/api/admin/events?${params.toString()}`)
}

function getAdminEvent(eventId) {
  return api(`/api/admin/events/${encodeURIComponent(eventId)}`)
}

function getAdminGalleries(filters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    params.set(key, String(value))
  })
  return api(`/api/admin/galleries?${params.toString()}`)
}

function getAdminGallery(galleryId) {
  return api(`/api/admin/galleries/${encodeURIComponent(galleryId)}`)
}

function patchGalleryModeration(galleryId, payload) {
  return api(`/api/admin/galleries/${encodeURIComponent(galleryId)}/moderation`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

function patchBulkGalleryModeration(payload) {
  return api('/api/admin/galleries/bulk-moderation', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

function patchEventModeration(eventId, payload) {
  return api(`/api/admin/events/${encodeURIComponent(eventId)}/moderation`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

function patchBulkEventModeration(payload) {
  return api('/api/admin/events/bulk-moderation', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

function getAdminModerationMetrics() {
  return api('/api/admin/moderation/metrics')
}

function autoApplyEventSuggestions(payload) {
  return api('/api/admin/events/auto-apply-suggestions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

function eventModerationStatusLabel(event) {
  return event.is_hidden ? 'Hidden' : event.is_approved ? 'Approved' : event.moderation_override_exists ? 'Reviewed' : 'Unmoderated'
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
      <Link to="/admin/events">Events</Link>
      <Link to="/admin/galleries">Galleries</Link>
      <Link to="/admin/moderation-dashboard">Dashboard</Link>
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
  const [showRawBio, setShowRawBio] = React.useState(false)

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
  const cleanedBio = artist.cleaned_artist_bio || ''
  const currentBio = cleanedBio || artist.artist_bio || ''
  const rawBio = artist.original_artist_bio || ''
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
      {artist.is_hidden && (
        <p className="moderation-warning">This artist is hidden from browsing.</p>
      )}
      {artist.canonical_artist_name && (
        <p><strong>Canonical artist name:</strong> {artist.canonical_artist_name}</p>
      )}
      <p><strong>Artwork count:</strong> {artist.artwork_count ?? artworks.length ?? 0}</p>
      {typeof artist.bio_quality_score === 'number' && (
        <p>
          <strong>Bio quality score:</strong>{' '}
          <span className="quality-badge">{artist.bio_quality_score}</span>
        </p>
      )}
      {Array.isArray(artist.bio_quality_flags) && artist.bio_quality_flags.length > 0 && (
        <p><strong>Bio flags:</strong> {artist.bio_quality_flags.join(', ')}</p>
      )}
      <p><strong>Current bio:</strong> {currentBio || 'No bio available'}</p>
      {rawBio && (
        <div className="controls">
          <button onClick={() => setShowRawBio((value) => !value)}>
            {showRawBio ? 'Hide raw bio' : 'Show raw bio'}
          </button>
          {showRawBio && (
            <p>
              <strong>Raw bio:</strong> {rawBio}
            </p>
          )}
        </div>
      )}
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
              {event.event_id && <p><Link to={`/admin/events/${event.event_id}`}>Open admin event</Link></p>}
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
  'artists-poor-bio': { title: 'Poor bios', summaryKey: 'artists_poor_bio', issueType: 'poor_bio_quality', type: 'artist' },
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

function ModerationQueueList({ queueName, items, onRefresh }) {
  const config = MODERATION_QUEUE_CONFIG[queueName]
  if (!config) return <p className="error-text">Unknown queue.</p>
  if (items.length === 0) return <p>No records in this queue.</p>

  async function toggleHidden(artistName, isHidden) {
    await updateArtistModeration(artistName, {
      is_hidden: isHidden,
      reason: isHidden ? 'Hidden from moderation queue' : 'Unhidden from moderation queue',
      updated_by: 'admin',
    })
    onRefresh()
  }

  async function setCanonical(artistName) {
    const canonical = window.prompt(`Canonical artist name for "${artistName}"?`)
    if (canonical === null) return
    await updateArtistModeration(artistName, {
      is_hidden: false,
      canonical_artist_name: canonical.trim() || null,
      reason: 'Canonical name set from moderation queue',
      updated_by: 'admin',
    })
    onRefresh()
  }

  async function reviewArtwork(item, type) {
    const notes = window.prompt(`${type === 'approve' ? 'Approval' : 'Rejection'} notes`, '') ?? ''
    if (type === 'approve') {
      await approveArtwork(item.artwork_id, { reviewer: 'admin', notes })
    } else {
      await rejectArtwork(item.artwork_id, {
        reviewer: 'admin',
        notes,
        rejection_reason: notes || 'Rejected by admin',
      })
    }
    onRefresh()
  }

  return (
    <div className="queue-list">
      {items.map((item, idx) => (
        <article className="queue-item" key={`${item.artwork_id || item.artist_name || idx}-${idx}`}>
          <p><span className="issue-badge">{item.issue_reason || config.issueType}</span></p>
          {config.type === 'artist' ? (
            <>
              <h3><Link to={`/artists/${encodeURIComponent(item.artist_name)}`}>{item.artist_name || 'Unknown artist'}</Link></h3>
              <p><strong>Artworks:</strong> {item.artwork_count ?? 0}</p>
              {typeof item.bio_quality_score === 'number' && (
                <p><strong>Bio quality:</strong> <span className="quality-badge">{item.bio_quality_score}</span></p>
              )}
              {Array.isArray(item.bio_quality_flags) && item.bio_quality_flags.length > 0 && (
                <p><strong>Flags:</strong> {item.bio_quality_flags.join(', ')}</p>
              )}
              <p>{item.cleaned_artist_bio ? `${item.cleaned_artist_bio.slice(0, 220)}${item.cleaned_artist_bio.length > 220 ? '...' : ''}` : 'No cleaned bio available'}</p>
              {item.original_artist_bio && <p><strong>Raw:</strong> {item.original_artist_bio.slice(0, 160)}{item.original_artist_bio.length > 160 ? '...' : ''}</p>}
              {item.edited_bio && <p><strong>Manual bio set.</strong> {item.edited_by ? `By ${item.edited_by}` : ''} {item.edited_at || ''}</p>}
              <p className="flag-status">Open flags: {item.open_flags_count ?? 0}</p>
              {item.is_hidden ? <span className="hidden-badge">Hidden</span> : null}
              {item.canonical_artist_name ? <p><strong>Canonical:</strong> {item.canonical_artist_name}</p> : null}
              {item.profile_url && <p><a href={item.profile_url} target="_blank" rel="noreferrer">Profile source</a></p>}
              <div className="action-row">
                <Link to={`/artists/${encodeURIComponent(item.artist_name)}`}>Open artist profile</Link>
                <Link to={`/artists/${encodeURIComponent(item.artist_name)}`}>Edit bio</Link>
                <button onClick={() => toggleHidden(item.artist_name, !item.is_hidden)}>{item.is_hidden ? 'Unhide artist' : 'Hide artist'}</button>
                <button onClick={() => setCanonical(item.artist_name)}>Set canonical artist name</button>
              </div>
            </>
          ) : (
            <>
              {item.image_url ? <img src={item.image_url} alt={item.artwork_title || 'Artwork'} /> : <div className="image-fallback">No image</div>}
              <h3>{item.artwork_title || 'Untitled artwork'}</h3>
              <p><strong>Artist:</strong> <Link to={`/artists/${encodeURIComponent(item.artist_name || '')}`}>{item.artist_name || 'Unknown artist'}</Link></p>
              <p><strong>Status:</strong> {item.review_status || 'pending'}</p>
              {item.rejection_reason && <p><strong>Rejection reason:</strong> {item.rejection_reason}</p>}
              {item.source_url && <p><a href={item.source_url} target="_blank" rel="noreferrer">Source URL</a></p>}
              <div className="action-row">
                {item.artwork_id && <Link to={`/artworks/${item.artwork_id}`}>Open artwork detail</Link>}
                {item.artwork_id && <button onClick={() => reviewArtwork(item, 'approve')}>Approve artwork</button>}
                {item.artwork_id && <button onClick={() => reviewArtwork(item, 'reject')}>Reject artwork</button>}
              </div>
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
  const [flags, setFlags] = React.useState([])
  const [loadingSummary, setLoadingSummary] = React.useState(true)
  const [loadingQueue, setLoadingQueue] = React.useState(false)
  const [loadingFlags, setLoadingFlags] = React.useState(false)
  const [error, setError] = React.useState('')
  const selectedQueue = searchParams.get('queue') || ''
  const tab = searchParams.get('tab') || 'queues'
  const status = searchParams.get('status') || (tab === 'resolved' ? 'resolved' : 'open')

  const loadSummary = React.useCallback(() => {
    let mounted = true
    setLoadingSummary(true)
    getModerationSummary()
      .then((json) => mounted && setSummary(json || {}))
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoadingSummary(false))
    return () => { mounted = false }
  }, [])
  React.useEffect(() => loadSummary(), [loadSummary])

  const loadQueue = React.useCallback(() => {
    if (!selectedQueue) {
      setRecords([])
      return () => {}
    }
    let mounted = true
    setLoadingQueue(true)
    setError('')
    getModerationQueue(selectedQueue, { limit: 100, offset: 0, status })
      .then((json) => mounted && setRecords(Array.isArray(json) ? json : []))
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoadingQueue(false))
    return () => { mounted = false }
  }, [selectedQueue, status])
  React.useEffect(() => loadQueue(), [loadQueue])

  React.useEffect(() => {
    if (tab === 'queues') return
    let mounted = true
    setLoadingFlags(true)
    getModerationFlags({ status: tab === 'resolved' ? 'resolved' : 'open', limit: 200 })
      .then((json) => mounted && setFlags(Array.isArray(json) ? json : []))
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoadingFlags(false))
    return () => { mounted = false }
  }, [tab])

  async function toggleFlag(flag, action) {
    if (action === 'resolve') {
      await resolveModerationFlag(flag.id, { resolved_by: 'admin', resolution_notes: 'Resolved from moderation UI' })
    } else {
      await reopenModerationFlag(flag.id, { reopened_by: 'admin', notes: 'Reopened from moderation UI' })
    }
    const nextStatus = tab === 'resolved' ? 'resolved' : 'open'
    const updated = await getModerationFlags({ status: nextStatus, limit: 200 })
    setFlags(Array.isArray(updated) ? updated : [])
    loadSummary()
    loadQueue()
  }

  return (
    <section>
      <h2>Moderation</h2>
      <div className="action-row">
        <button onClick={() => setSearchParams({ tab: 'queues', queue: selectedQueue, status })}>Queues</button>
        <button onClick={() => setSearchParams({ tab: 'flags', status: 'open' })}>Flags</button>
        <button onClick={() => setSearchParams({ tab: 'resolved', status: 'resolved' })}>Resolved</button>
      </div>
      {loadingSummary && <p>Loading moderation queues...</p>}
      {error && <p className="error-text">Failed to load moderation data: {error}</p>}
      {tab === 'queues' && (
        <>
          <div className="action-row">
            <button onClick={() => setSearchParams({ tab: 'queues', queue: selectedQueue, status: 'open' })}>Open</button>
            <button onClick={() => setSearchParams({ tab: 'queues', queue: selectedQueue, status: 'resolved' })}>Resolved</button>
            <button onClick={() => setSearchParams({ tab: 'queues', queue: selectedQueue, status: 'all' })}>All</button>
          </div>
          <div className="moderation-grid">
            {Object.entries(MODERATION_QUEUE_CONFIG).map(([queueName, config]) => (
              <article className="moderation-card" key={queueName}>
                <h3>{config.title}</h3>
                <p>{summary?.[config.summaryKey] ?? 0}</p>
                <button onClick={() => setSearchParams({ tab: 'queues', queue: queueName, status })}>Open queue</button>
              </article>
            ))}
          </div>
          {selectedQueue && (
            <>
              <h3>{MODERATION_QUEUE_CONFIG[selectedQueue]?.title || selectedQueue}</h3>
              {loadingQueue ? <p>Loading queue records...</p> : <ModerationQueueList queueName={selectedQueue} items={records} onRefresh={loadQueue} />}
            </>
          )}
        </>
      )}
      {tab !== 'queues' && (
        <div>
          {loadingFlags ? <p>Loading flags...</p> : (
            <div className="queue-list">
              {flags.map((flag) => (
                <article className="queue-item" key={flag.id}>
                  <p><span className={`flag-status ${flag.status === 'resolved' ? 'resolved-badge' : ''}`}>{flag.status}</span></p>
                  <p><strong>Entity:</strong> {flag.entity_type} {flag.entity_id || ''}</p>
                  <p><strong>Artist:</strong> {flag.artist_name || '-'}</p>
                  <p><strong>Issue:</strong> {flag.issue_type}</p>
                  <p><strong>Notes:</strong> {flag.notes || '-'}</p>
                  <p><strong>Created:</strong> {flag.created_by || '-'} / {flag.created_at || '-'}</p>
                  <div className="action-row">
                    {flag.status !== 'resolved' && <button onClick={() => toggleFlag(flag, 'resolve')}>Resolve</button>}
                    {flag.status === 'resolved' && <button onClick={() => toggleFlag(flag, 'reopen')}>Reopen</button>}
                  </div>
                </article>
              ))}
              {flags.length === 0 && <p>No flags found.</p>}
            </div>
          )}
        </div>
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
    if (type === 'approve') await approveArtwork(artworkId, body)
    if (type === 'reject') await rejectArtwork(artworkId, body)
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

function AdminEventsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [events, setEvents] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [saveError, setSaveError] = React.useState('')
  const [selectedEventIds, setSelectedEventIds] = React.useState(new Set())
  const [bulkEventType, setBulkEventType] = React.useState('')
  const [autoApplyPreview, setAutoApplyPreview] = React.useState(null)
  const [activeIndex, setActiveIndex] = React.useState(0)
  const [showShortcutHelp, setShowShortcutHelp] = React.useState(false)
  const searchInputRef = React.useRef(null)
  const typeSelectRefs = React.useRef({})
  const titleInputRefs = React.useRef({})

  const filters = React.useMemo(() => ({
    queue: searchParams.get('queue') || 'needs_review',
    event_type: searchParams.get('event_type') || '',
    source_domain: searchParams.get('source_domain') || '',
    missing_date: searchParams.get('missing_date') === 'true',
    missing_venue: searchParams.get('missing_venue') === 'true',
    include_hidden: searchParams.get('include_hidden') !== 'false',
    search: searchParams.get('search') || '',
    limit: 100,
    offset: 0,
  }), [searchParams])

  React.useEffect(() => {
    let mounted = true
    setLoading(true)
    setError('')
    getAdminEvents(filters)
      .then((json) => {
        if (!mounted) return
        setEvents(Array.isArray(json) ? json : [])
        setSelectedEventIds(new Set())
        setActiveIndex(0)
      })
      .catch((err) => mounted && setError(err.message))
      .finally(() => mounted && setLoading(false))
    return () => { mounted = false }
  }, [filters])

  const availableEventTypes = React.useMemo(() => {
    const fromData = events
      .map((event) => event.event_type || event.canonical_event_type || event.original_event_type)
      .filter(Boolean)
    return Array.from(new Set(['exhibition', 'fair', 'talk', 'auction', ...fromData]))
  }, [events])

  const selectedCount = selectedEventIds.size
  const allVisibleSelected = events.length > 0 && events.every((event) => selectedEventIds.has(event.event_id))
  const activeEvent = events[activeIndex] || null

  function updateEventRow(eventId, updates) {
    setEvents((current) => current.map((event) => (event.event_id === eventId ? { ...event, ...updates } : event)))
  }

  function updateFilter(key, value) {
    const next = new URLSearchParams(searchParams)
    if (value === '' || value === null) next.delete(key)
    else next.set(key, String(value))
    setSearchParams(next)
  }

  function toggleSelected(eventId, checked) {
    setSelectedEventIds((current) => {
      const next = new Set(current)
      if (checked) next.add(eventId)
      else next.delete(eventId)
      return next
    })
  }

  function toggleSelectAllVisible(checked) {
    if (checked) {
      setSelectedEventIds(new Set(events.map((event) => event.event_id)))
      return
    }
    setSelectedEventIds(new Set())
  }

  async function saveSingleEvent(eventId, updates) {
    try {
      setSaving(true)
      setSaveError('')
      const result = await patchEventModeration(eventId, updates)
      updateEventRow(eventId, result.event_moderation || updates)
    } catch (err) {
      setSaveError(`Failed to update event ${eventId}: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  async function runBulkUpdate(updates) {
    if (selectedEventIds.size === 0) return
    const eventIds = Array.from(selectedEventIds)
    setSaving(true)
    setSaveError('')
    try {
      try {
        const result = await patchBulkEventModeration({ event_ids: eventIds, updates })
        if (result.failed?.length) {
          setSaveError(`Updated ${result.updated} events, ${result.failed.length} failed.`)
        }
      } catch (bulkErr) {
        await Promise.all(eventIds.map((eventId) => patchEventModeration(eventId, updates)))
      }
      setEvents((current) => current.map((event) => (
        selectedEventIds.has(event.event_id)
          ? { ...event, ...updates, event_type: updates.event_type ?? event.event_type }
          : event
      )))
    } catch (err) {
      setSaveError(`Bulk update failed: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  async function applySuggestion(event) {
    const updates = {}
    if (event.suggested_event_type) updates.event_type = event.suggested_event_type
    if (event.suggested_event_title) updates.canonical_event_title = event.suggested_event_title
    if (Object.keys(updates).length === 0) return
    await saveSingleEvent(event.event_id, updates)
  }

  async function applyVisibleSuggestions() {
    const candidates = events.filter((event) => event.suggested_event_type || event.suggested_event_title)
    for (const event of candidates) {
      // eslint-disable-next-line no-await-in-loop
      await applySuggestion(event)
    }
  }

  async function runAutoApply(dryRun) {
    try {
      setSaving(true)
      setSaveError('')
      const result = await autoApplyEventSuggestions({ dry_run: dryRun, limit: 500, queue: filters.queue })
      setAutoApplyPreview(result)
      if (!dryRun) {
        const refreshed = await getAdminEvents(filters)
        setEvents(Array.isArray(refreshed) ? refreshed : [])
      }
    } catch (err) {
      setSaveError(`Auto-apply failed: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  React.useEffect(() => {
    function isTypingTarget(target) {
      if (!target) return false
      const tag = target.tagName?.toLowerCase()
      return target.isContentEditable || tag === 'input' || tag === 'textarea' || tag === 'select'
    }

    function withSelectedOrActive() {
      if (selectedEventIds.size > 0) return Array.from(selectedEventIds)
      return activeEvent?.event_id ? [activeEvent.event_id] : []
    }

    function onKeydown(event) {
      if (isTypingTarget(event.target)) return
      if (event.key === '?') {
        event.preventDefault()
        setShowShortcutHelp((current) => !current)
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        setSelectedEventIds(new Set())
        setShowShortcutHelp(false)
        return
      }
      if (event.key === '/') {
        event.preventDefault()
        searchInputRef.current?.focus()
        return
      }
      if (event.key === 'j') {
        event.preventDefault()
        setActiveIndex((current) => Math.min(events.length - 1, current + 1))
        return
      }
      if (event.key === 'k') {
        event.preventDefault()
        setActiveIndex((current) => Math.max(0, current - 1))
        return
      }
      if (event.key === ' ') {
        event.preventDefault()
        if (!activeEvent) return
        toggleSelected(activeEvent.event_id, !selectedEventIds.has(activeEvent.event_id))
        return
      }
      if (event.key === 't') {
        event.preventDefault()
        if (activeEvent) typeSelectRefs.current[activeEvent.event_id]?.focus()
        return
      }
      if (event.key === 'e') {
        event.preventDefault()
        if (activeEvent) titleInputRefs.current[activeEvent.event_id]?.focus()
        return
      }
      if (['a', 'h', 'u', 'r'].includes(event.key)) {
        event.preventDefault()
        const targets = withSelectedOrActive()
        if (targets.length === 0) return
        const updates = event.key === 'a'
          ? { is_approved: true, is_hidden: false }
          : event.key === 'h'
            ? { is_hidden: true }
            : event.key === 'u'
              ? { is_hidden: false }
              : { is_approved: false }
        setSelectedEventIds(new Set(targets))
        runBulkUpdate(updates)
      }
    }
    window.addEventListener('keydown', onKeydown)
    return () => window.removeEventListener('keydown', onKeydown)
  }, [events, selectedEventIds, activeEvent])

  const queueTabs = ['needs_review', 'low_quality', 'recent', 'approved', 'hidden', 'edited', 'all']

  return (
    <section>
      <h2>Events moderation</h2>
      <div className="queue-tabs">
        {queueTabs.map((queue) => (
          <button
            key={queue}
            className={filters.queue === queue ? 'active-tab' : ''}
            onClick={() => updateFilter('queue', queue)}
          >
            {queue.replace('_', ' ')}
          </button>
        ))}
      </div>
      <div className="controls">
        <input
          ref={searchInputRef}
          type="search"
          placeholder="Search title or source URL"
          value={filters.search}
          onChange={(e) => updateFilter('search', e.target.value)}
        />
        <input
          type="text"
          placeholder="Event type"
          value={filters.event_type}
          onChange={(e) => updateFilter('event_type', e.target.value)}
        />
        <input
          type="text"
          placeholder="Source domain"
          value={filters.source_domain}
          onChange={(e) => updateFilter('source_domain', e.target.value)}
        />
        <label><input type="checkbox" checked={filters.missing_date} onChange={(e) => updateFilter('missing_date', e.target.checked)} /> Missing date</label>
        <label><input type="checkbox" checked={filters.missing_venue} onChange={(e) => updateFilter('missing_venue', e.target.checked)} /> Missing venue</label>
        <label><input type="checkbox" checked={filters.include_hidden} onChange={(e) => updateFilter('include_hidden', e.target.checked)} /> Show hidden</label>
      </div>
      {loading && <p>Loading events…</p>}
      {error && <p className="error-text">Failed to load events: {error}</p>}
      {saveError && <p className="error-text">{saveError}</p>}
      {autoApplyPreview && (
        <div className="auto-apply-panel">
          <strong>Auto-apply result</strong>
          <div>Eligible: {autoApplyPreview.eligible} · Would update: {autoApplyPreview.would_update} · Updated: {autoApplyPreview.updated}</div>
          {Array.isArray(autoApplyPreview.examples) && autoApplyPreview.examples.length > 0 && (
            <ul>
              {autoApplyPreview.examples.slice(0, 5).map((item) => (
                <li key={item.event_id}>{item.event_title || item.event_id}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <p className="help-text">Keyboard shortcuts: ? for help.</p>
      {!loading && !error && (
        <table>
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={(e) => toggleSelectAllVisible(e.target.checked)}
                  aria-label="Select all visible events"
                />
              </th>
              <th>Title</th><th>Type</th><th>Artists</th><th>Venue</th><th>City</th><th>Dates</th><th>Source</th><th>Crawl</th><th>Status</th><th>Inline moderation</th>
            </tr>
          </thead>
          <tbody>
            {selectedCount > 0 && (
              <tr>
                <td colSpan={11}>
                  <div className="action-row">
                    <strong>{selectedCount} selected</strong>
                    <button disabled={saving} onClick={() => runBulkUpdate({ is_approved: true })}>Approve selected</button>
                    <button disabled={saving} onClick={() => runBulkUpdate({ is_hidden: true })}>Hide selected</button>
                    <button disabled={saving} onClick={() => runBulkUpdate({ is_hidden: false })}>Unhide selected</button>
                    <button disabled={saving} onClick={() => runBulkUpdate({ is_approved: false })}>Mark unapproved</button>
                    <button disabled={saving} onClick={applyVisibleSuggestions}>Apply visible suggestions</button>
                    <button disabled={saving} onClick={() => runAutoApply(true)}>Dry run auto-apply</button>
                    <button disabled={saving} onClick={() => runAutoApply(false)}>Apply high-confidence suggestions</button>
                    <select value={bulkEventType} onChange={(e) => setBulkEventType(e.target.value)} disabled={saving}>
                      <option value="">Set event type…</option>
                      {availableEventTypes.map((type) => <option key={type} value={type}>{type}</option>)}
                    </select>
                    <button disabled={saving || !bulkEventType} onClick={() => runBulkUpdate({ event_type: bulkEventType })}>
                      Apply type
                    </button>
                  </div>
                </td>
              </tr>
            )}
            {events.map((event, idx) => (
              <tr key={event.event_id} className={idx === activeIndex ? 'active-row' : ''} onClick={() => setActiveIndex(idx)}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedEventIds.has(event.event_id)}
                    onChange={(e) => toggleSelected(event.event_id, e.target.checked)}
                    aria-label={`Select ${event.event_title || event.original_event_title || 'event'}`}
                  />
                </td>
                <td><Link to={`/admin/events/${event.event_id}`}>{event.event_title || event.original_event_title || 'Untitled event'}</Link></td>
                <td>{event.event_type || event.canonical_event_type || 'Unknown'}</td>
                <td>{Array.isArray(event.linked_artists) && event.linked_artists.length > 0 ? event.linked_artists.join(', ') : '—'}</td>
                <td>{event.venue_name || 'Missing venue'}</td>
                <td>{event.city || '—'}</td>
                <td>{event.start_date || 'Missing'}{event.end_date ? ` → ${event.end_date}` : ''}</td>
                <td>{event.source_domain || event.source_name}</td>
                <td>{event.crawl_timestamp || '—'}</td>
                <td>
                  {eventModerationStatusLabel(event)}
                  {String(event.moderation_reason || '').startsWith('auto_applied') && (
                    <div><small className="auto-badge">auto-applied</small></div>
                  )}
                  <div className="quality-meta">
                    <span className="quality-badge">{event.quality_score}/5</span>
                    {Array.isArray(event.quality_flags) && event.quality_flags.length > 0 && (
                      <small>{event.quality_flags.join(', ')}</small>
                    )}
                  </div>
                </td>
                <td>
                  <div className="inline-controls">
                    <label>
                      <input
                        type="checkbox"
                        checked={Boolean(event.is_approved)}
                        disabled={saving}
                        onChange={(e) => saveSingleEvent(event.event_id, { is_approved: e.target.checked })}
                      />
                      Approve
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={Boolean(event.is_hidden)}
                        disabled={saving}
                        onChange={(e) => saveSingleEvent(event.event_id, { is_hidden: e.target.checked })}
                      />
                      Hide
                    </label>
                    <select
                      ref={(el) => { typeSelectRefs.current[event.event_id] = el }}
                      value={event.event_type || ''}
                      disabled={saving}
                      onChange={(e) => saveSingleEvent(event.event_id, { event_type: e.target.value })}
                    >
                      <option value="">Event type…</option>
                      {availableEventTypes.map((type) => <option key={type} value={type}>{type}</option>)}
                    </select>
                    <div className="inline-title-edit">
                      <input
                        ref={(el) => { titleInputRefs.current[event.event_id] = el }}
                        type="text"
                        defaultValue={event.canonical_event_title || event.event_title || ''}
                        disabled={saving}
                        placeholder="Canonical title"
                        onBlur={(e) => {
                          if ((event.canonical_event_title || event.event_title || '') !== e.target.value) {
                            saveSingleEvent(event.event_id, { canonical_event_title: e.target.value })
                          }
                        }}
                      />
                    </div>
                    {(event.suggested_event_type || event.suggested_event_title) && (
                      <>
                        <small>
                          {event.suggested_event_type ? `Suggested: ${event.suggested_event_type} · ${Math.round((event.event_type_confidence || 0) * 100)}%` : ''}
                          {event.suggested_event_title ? ` ${event.suggested_event_title} · ${Math.round((event.event_title_confidence || 0) * 100)}%` : ''}
                        </small>
                        <small>{event.event_type_suggestion_reason || event.event_title_suggestion_reason || event.suggestion_reason}</small>
                        <button disabled={saving} onClick={() => applySuggestion(event)}>
                          Apply suggestion
                        </button>
                      </>
                    )}
                    {String(event.moderation_reason || '').startsWith('auto_applied') && (
                      <button disabled={saving} onClick={() => saveSingleEvent(event.event_id, {
                        canonical_event_title: '',
                        event_type: '',
                        moderation_reason: 'reverted auto_applied suggestion',
                      })}
                      >
                        Undo auto-apply
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {showShortcutHelp && (
        <div className="shortcut-modal">
          <h3>Keyboard shortcuts</h3>
          <ul>
            <li>j / k: move active row</li><li>space: select active row</li><li>a: approve selected or active</li>
            <li>h: hide selected or active</li><li>u: unhide selected or active</li><li>r: reset approval</li>
            <li>t: focus type</li><li>e: focus canonical title</li><li>/: focus search</li>
            <li>esc: clear selection</li><li>?: toggle this help</li>
          </ul>
        </div>
      )}
    </section>
  )
}

function AdminEventDetailPage() {
  const { eventId = '' } = useParams()
  const [detail, setDetail] = React.useState(null)
  const [error, setError] = React.useState('')
  const [loading, setLoading] = React.useState(true)
  const [saveStatus, setSaveStatus] = React.useState('')

  const loadEvent = React.useCallback(() => {
    setLoading(true)
    setError('')
    getAdminEvent(eventId)
      .then(setDetail)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [eventId])

  React.useEffect(() => { loadEvent() }, [loadEvent])

  async function updateModeration(changes) {
    try {
      setSaveStatus('')
      await patchEventModeration(eventId, changes)
      setSaveStatus('Moderation saved.')
      loadEvent()
    } catch (err) {
      setSaveStatus(`Failed to save moderation: ${err.message}`)
    }
  }

  if (loading) return <section><h2>Event detail</h2><p>Loading…</p></section>
  if (error || !detail?.event) return <section><h2>Event detail</h2><p className="error-text">{error || 'Not found'}</p></section>

  const event = detail.event
  const linkedArtists = detail.linked_artists || []

  return (
    <section>
      <p><Link to="/admin/events">← Back to events</Link></p>
      <h2>{event.event_title || 'Untitled event'}</h2>
      <p><strong>Type:</strong> {event.event_type || 'Unknown'}</p>
      <p><strong>Venue:</strong> {event.venue_name || 'Missing venue'}</p>
      <p><strong>City/Country:</strong> {[event.city, event.country].filter(Boolean).join(', ') || '—'}</p>
      <p><strong>Dates:</strong> {event.start_date || 'Missing'}{event.end_date ? ` → ${event.end_date}` : ''}</p>
      {event.source_url && <p><a href={event.source_url} target="_blank" rel="noreferrer">Source URL</a></p>}
      <p><strong>Status:</strong> {event.is_hidden ? 'Hidden' : event.is_approved ? 'Approved' : event.moderation_override_exists ? 'Reviewed' : 'Unmoderated'}</p>

      <h3>Linked artists</h3>
      {linkedArtists.length === 0 ? <p>No linked artists.</p> : (
        <ul>
          {linkedArtists.map((artist) => (
            <li key={artist.artist_activity_id || `${artist.artist_name}-${artist.source_url}`}>
              {artist.artist_name ? <Link to={`/artists/${encodeURIComponent(artist.artist_name)}`}>{artist.artist_name}</Link> : 'Unknown artist'}
              {artist.artist_profile_url ? <> — <a href={artist.artist_profile_url} target="_blank" rel="noreferrer">Profile</a></> : null}
            </li>
          ))}
        </ul>
      )}
      {detail.linked_gallery && (
        <p>
          <strong>Gallery:</strong>{' '}
          <Link to={`/admin/galleries/${detail.linked_gallery.gallery_id}`}>
            {detail.linked_gallery.gallery_name || detail.linked_gallery.gallery_id}
          </Link>
        </p>
      )}

      <h3>Moderation controls</h3>
      <div className="action-row">
        <button onClick={() => updateModeration({ is_approved: !event.is_approved })}>
          {event.is_approved ? 'Unapprove' : 'Approve'}
        </button>
        <button onClick={() => updateModeration({ is_hidden: !event.is_hidden })}>
          {event.is_hidden ? 'Unhide' : 'Hide'}
        </button>
        <button onClick={() => {
          const canonical = window.prompt('Canonical event title', event.canonical_event_title || event.event_title || '')
          if (canonical !== null) updateModeration({ canonical_event_title: canonical })
        }}>Set canonical title</button>
        <button onClick={() => {
          const eventType = window.prompt('Event type override', event.event_type || '')
          if (eventType !== null) updateModeration({ event_type: eventType })
        }}>Set event type</button>
      </div>
      <div className="controls">
        <button onClick={() => {
          const reason = window.prompt('Moderation reason', event.moderation_reason || '')
          if (reason !== null) updateModeration({ moderation_reason: reason })
        }}>Edit reason</button>
        <button onClick={() => {
          const notes = window.prompt('Moderator notes', event.moderator_notes || '')
          if (notes !== null) updateModeration({ moderator_notes: notes })
        }}>Edit notes</button>
      </div>
      {saveStatus && <p className={saveStatus.startsWith('Failed') ? 'error-text' : ''}>{saveStatus}</p>}

      <h3>Raw metadata</h3>
      <pre>{JSON.stringify(event.raw_payload || {}, null, 2)}</pre>
    </section>
  )
}

function AdminGalleriesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [rows, setRows] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [selected, setSelected] = React.useState(new Set())
  const [saving, setSaving] = React.useState(false)

  const filters = React.useMemo(() => ({
    queue: searchParams.get('queue') || 'needs_review',
    search: searchParams.get('search') || '',
    source_domain: searchParams.get('source_domain') || '',
    missing_address: searchParams.get('missing_address') === 'true',
    missing_city: searchParams.get('missing_city') === 'true',
    missing_country: searchParams.get('missing_country') === 'true',
    include_hidden: searchParams.get('include_hidden') !== 'false',
    limit: 100,
    offset: 0,
  }), [searchParams])

  React.useEffect(() => {
    setLoading(true)
    getAdminGalleries(filters)
      .then((json) => { setRows(Array.isArray(json) ? json : []); setSelected(new Set()) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [filters])

  const queueTabs = ['needs_review', 'low_quality', 'recent', 'approved', 'hidden', 'edited', 'all']

  function updateFilter(key, value) {
    const next = new URLSearchParams(searchParams)
    if (value === '' || value === null) next.delete(key)
    else next.set(key, String(value))
    setSearchParams(next)
  }

  function toggleSelect(id, checked) {
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  async function runBulk(updates) {
    if (selected.size === 0) return
    setSaving(true)
    try {
      await patchBulkGalleryModeration({ gallery_ids: Array.from(selected), updates })
      setRows((current) => current.map((row) => (selected.has(row.gallery_id) ? { ...row, ...updates } : row)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section>
      <h2>Galleries moderation</h2>
      <div className="queue-tabs">
        {queueTabs.map((queue) => <button key={queue} className={filters.queue === queue ? 'active-tab' : ''} onClick={() => updateFilter('queue', queue)}>{queue.replace('_', ' ')}</button>)}
      </div>
      <div className="controls">
        <input type="search" placeholder="Search galleries" value={filters.search} onChange={(e) => updateFilter('search', e.target.value)} />
        <input type="text" placeholder="Source domain" value={filters.source_domain} onChange={(e) => updateFilter('source_domain', e.target.value)} />
        <label><input type="checkbox" checked={filters.missing_address} onChange={(e) => updateFilter('missing_address', e.target.checked)} /> Missing address</label>
        <label><input type="checkbox" checked={filters.missing_city} onChange={(e) => updateFilter('missing_city', e.target.checked)} /> Missing city</label>
        <label><input type="checkbox" checked={filters.missing_country} onChange={(e) => updateFilter('missing_country', e.target.checked)} /> Missing country</label>
      </div>
      {loading && <p>Loading galleries…</p>}
      {error && <p className="error-text">{error}</p>}
      {!loading && !error && (
        <table>
          <thead>
            <tr>
              <th />
              <th>Gallery</th>
              <th>City</th>
              <th>Country</th>
              <th>Source</th>
              <th>Quality</th>
              <th>Flags</th>
              <th>Moderation</th>
            </tr>
          </thead>
          <tbody>
            {selected.size > 0 && (
              <tr><td colSpan={8}><div className="action-row"><strong>{selected.size} selected</strong><button disabled={saving} onClick={() => runBulk({ is_approved: true, is_hidden: false })}>Approve</button><button disabled={saving} onClick={() => runBulk({ is_hidden: true })}>Hide</button><button disabled={saving} onClick={() => runBulk({ is_hidden: false })}>Unhide</button></div></td></tr>
            )}
            {rows.map((gallery) => (
              <tr key={gallery.gallery_id}>
                <td><input type="checkbox" checked={selected.has(gallery.gallery_id)} onChange={(e) => toggleSelect(gallery.gallery_id, e.target.checked)} /></td>
                <td><Link to={`/admin/galleries/${gallery.gallery_id}`}>{gallery.canonical_gallery_name || gallery.gallery_name || 'Unknown gallery'}</Link></td>
                <td>{gallery.city || '—'}</td>
                <td>{gallery.country || '—'}</td>
                <td>{gallery.source_domain || '—'}</td>
                <td><span className="quality-badge">{gallery.quality_score}/6</span></td>
                <td>{gallery.quality_flags?.join(', ') || 'ok'}</td>
                <td>
                  <label><input type="checkbox" checked={Boolean(gallery.is_approved)} onChange={(e) => patchGalleryModeration(gallery.gallery_id, { is_approved: e.target.checked }).then(() => setRows((cur) => cur.map((row) => row.gallery_id === gallery.gallery_id ? { ...row, is_approved: e.target.checked } : row)))} />Approve</label>
                  <label><input type="checkbox" checked={Boolean(gallery.is_hidden)} onChange={(e) => patchGalleryModeration(gallery.gallery_id, { is_hidden: e.target.checked }).then(() => setRows((cur) => cur.map((row) => row.gallery_id === gallery.gallery_id ? { ...row, is_hidden: e.target.checked } : row)))} />Hide</label>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function AdminGalleryDetailPage() {
  const { galleryId = '' } = useParams()
  const [detail, setDetail] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [status, setStatus] = React.useState('')

  const load = React.useCallback(() => {
    setLoading(true)
    getAdminGallery(galleryId).then(setDetail).catch((err) => setError(err.message)).finally(() => setLoading(false))
  }, [galleryId])
  React.useEffect(() => { load() }, [load])
  if (loading) return <section><h2>Gallery detail</h2><p>Loading…</p></section>
  if (error || !detail?.gallery) return <section><h2>Gallery detail</h2><p className="error-text">{error || 'Not found'}</p></section>
  const gallery = detail.gallery
  async function update(changes) {
    try {
      await patchGalleryModeration(galleryId, changes)
      setStatus('Saved')
      load()
    } catch (err) {
      setStatus(err.message)
    }
  }
  return (
    <section>
      <p><Link to="/admin/galleries">← Back to galleries</Link></p>
      <h2>{gallery.canonical_gallery_name || gallery.gallery_name}</h2>
      <p><strong>Address:</strong> {gallery.canonical_address || gallery.gallery_address || 'Missing address'}</p>
      <p><strong>City/Country:</strong> {[gallery.canonical_city || gallery.city, gallery.canonical_country || gallery.country].filter(Boolean).join(', ') || '—'}</p>
      <div className="action-row">
        <button onClick={() => update({ is_approved: !gallery.is_approved })}>{gallery.is_approved ? 'Unapprove' : 'Approve'}</button>
        <button onClick={() => update({ is_hidden: !gallery.is_hidden })}>{gallery.is_hidden ? 'Unhide' : 'Hide'}</button>
        <button onClick={() => { const val = window.prompt('Canonical gallery name', gallery.canonical_gallery_name || gallery.gallery_name || ''); if (val !== null) update({ canonical_gallery_name: val }) }}>Set canonical name</button>
      </div>
      <h3>Linked events</h3>
      <ul>
        {(gallery.linked_events || []).map((event) => (
          <li key={event.event_id}>
            <Link to={`/admin/events/${event.event_id}`}>{event.event_title || event.event_id}</Link>
          </li>
        ))}
      </ul>
      {status && <p>{status}</p>}
    </section>
  )
}

function ModerationDashboardPage() {
  const [metrics, setMetrics] = React.useState(null)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    getAdminModerationMetrics().then(setMetrics).catch((err) => setError(err.message))
  }, [])

  if (error) return <section><h2>Moderation dashboard</h2><p className="error-text">{error}</p></section>
  if (!metrics?.events) return <section><h2>Moderation dashboard</h2><p>Loading…</p></section>

  return (
    <section>
      <h2>Moderation dashboard</h2>
      <div className="moderation-grid">
        {Object.entries(metrics.events).map(([key, value]) => (
          <article key={key} className="moderation-card">
            <h3>{key.replaceAll('_', ' ')}</h3>
            <p><strong>{value}</strong></p>
          </article>
        ))}
        {Object.entries(metrics.galleries || {}).map(([key, value]) => (
          <article key={`gallery-${key}`} className="moderation-card">
            <h3>gallery {key.replaceAll('_', ' ')}</h3>
            <p><strong>{value}</strong></p>
          </article>
        ))}
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
        <Route path="/admin/events" element={<AdminEventsPage />} />
        <Route path="/admin/events/:eventId" element={<AdminEventDetailPage />} />
        <Route path="/admin/galleries" element={<AdminGalleriesPage />} />
        <Route path="/admin/galleries/:galleryId" element={<AdminGalleryDetailPage />} />
        <Route path="/admin/moderation-dashboard" element={<ModerationDashboardPage />} />
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
