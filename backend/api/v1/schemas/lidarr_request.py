"""Schemas for the inline single-track Lidarr request feature.

Fork-only addition. Distinct from track_download.py (which proxies to
the yt-dlp-worker on gnat for YouTube/Spotify-resolved downloads).

This feature uses Lidarr's native indexer + download-client pipeline
(slskd / qBittorrent / etc.) to grab the requested track, leveraging
the track-monitored fork's PUT /track/monitor endpoint so that only
the requested track ends up on disk — sibling tracks in the same album
release are rejected at import by TrackMonitoredSpecification.

Requires lidarr_url to point at an instance running shaunrd0/Lidarr
(currently only lidarr-shared on gnat:8688).
"""

from __future__ import annotations

from infrastructure.msgspec_fastapi import AppStruct


class LidarrRequestRequest(AppStruct):
    """Inbound request from the frontend.

    album_mbid and track_mbid are required — they drive Lidarr's album
    lookup/add and the per-track identification.

    artist_mbid is optional and only used for diagnostic logging; Lidarr's
    album lookup already returns the artist MBID server-side and that's
    what we actually use for the add. Frontend callers without artist
    context (TopSongsList, etc.) can leave it null.
    """

    album_mbid: str
    track_mbid: str
    artist_mbid: str | None = None
    # Fallback for matching when track_mbid alone doesn't disambiguate.
    # Backend matcher tries them in order: foreignTrackId == track_mbid,
    # foreignRecordingId == track_mbid, position+disc, then track_title.
    # Frontend should send what it has — Popular Songs lists often lack
    # position/disc, album-detail pages have all four.
    track_position: int | None = None
    disc_number: int | None = None
    track_title: str | None = None


class LidarrRequestAccepted(AppStruct):
    """Returned 202 from the request endpoint.

    `command_id` is Lidarr's command queue ID for the AlbumSearch — clients
    can poll `/api/v1/command/{id}` against Lidarr directly if they want
    progress, but for now the UI just shows success/error and lets the
    download appear in the library when Lidarr finishes.
    """

    status: str
    album_id: int
    album_title: str
    track_id: int
    track_title: str
    other_tracks_unmonitored: int
    command_id: int | None = None
    note: str | None = None


class LidarrRequestTrackStatus(AppStruct):
    """Per-track status surfaced by GET /api/v1/lidarr-request/status.

    The frontend uses this to render the LidarrRequestButton in the right
    persistent state — checkmark for downloaded, hourglass for requested-
    but-not-yet-downloaded, idle for not-requested. Without this, the
    button only knows transient session state and forgets after refresh.

    position + disc_number are returned alongside recording_mbid because
    Lidarr's foreignRecordingId doesn't always equal MusicBrainz's
    recording_id (Lidarr sometimes maps to a different variant). The
    frontend prefers recording_mbid match but falls back to position+disc
    when recording_mbid lookup misses.
    """

    recording_mbid: str
    position: int
    disc_number: int
    monitored: bool
    has_file: bool


class LidarrRequestStatusResponse(AppStruct):
    """Returned by GET /api/v1/lidarr-request/status?album_mbid=X.

    in_library = album exists in Lidarr at all. If false, no tracks are
    requested (the button shows idle on every row). If true, walk `tracks`
    to find the per-track status keyed by recording_mbid.
    """

    in_library: bool
    tracks: list[LidarrRequestTrackStatus]
