"""Schemas for the inline track-download feature.

This is a fork-only addition. Requests are proxied to a yt-dlp-worker sidecar
on gnat which performs the actual yt-dlp call and post-download Lidarr/Plex
triggers. The library label (music | music-personal) is stamped server-side
from the MUSICSEERR_LIBRARY env var so that public musicseerr cannot drop
files into the personal library.

Search source: "youtube" (default; free-text yt-dlp search) or "spotify"
(Spotify Web API search; the worker resolves the chosen Spotify track to a
matching YouTube video at download time, transparently to the client).
"""

from __future__ import annotations

from typing import Literal

from infrastructure.msgspec_fastapi import AppStruct


SearchSource = Literal["youtube", "spotify"]


class TrackDownloadSearchRequest(AppStruct):
    query: str
    limit: int = 5
    source: SearchSource = "youtube"


class TrackDownloadCandidate(AppStruct):
    # video_id is a YouTube video ID when source="youtube" and a Spotify
    # track ID when source="spotify". The worker disambiguates by source.
    video_id: str
    url: str
    title: str
    source: SearchSource = "youtube"
    channel: str | None = None
    artist: str | None = None  # populated for source="spotify"
    album: str | None = None  # populated for source="spotify"
    duration_seconds: int | None = None
    thumbnail_url: str | None = None


class TrackDownloadSearchResponse(AppStruct):
    candidates: list[TrackDownloadCandidate]


class TrackDownloadRequest(AppStruct):
    """Inbound request from the frontend. The library param is intentionally
    NOT included here — the backend stamps it from env config so the public
    musicseerr instance cannot target the personal library."""

    video_id: str
    artist: str
    album: str
    track_title: str
    source: SearchSource = "youtube"
    target_duration_seconds: int | None = None  # passed through for spotify→yt resolution
    artist_mbid: str | None = None
    track_position: int | None = None
    disc_number: int | None = None


class TrackDownloadAccepted(AppStruct):
    job_id: str


class TrackDownloadJobStatus(AppStruct):
    id: str
    status: str
    artist: str
    album: str
    track_title: str
    library: str
    created_at: str
    updated_at: str
    file_path: str | None = None
    error: str | None = None
