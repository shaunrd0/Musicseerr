"""TrackDownloadService — proxies inline track-download requests to the
yt-dlp-worker sidecar (on gnat). Library label is stamped from env config
so the public musicseerr instance cannot reach Music-Personal.

Also fires a scoped Lidarr RefreshArtist the FIRST TIME a job status flips
to "done" — so the new file gets picked up immediately instead of waiting
for Lidarr's next scheduled scan (which could be hours). Without this, the
file lands on disk but Lidarr's DB doesn't know about it, and the resolve
endpoint may either miss it (track not playable) or worse — return a stale
track_file_id whose path no longer exists (we hit this 2026-05-25 after a
drive swap).

Fork-only addition; do not entangle with services/youtube_service.py
(which uses the YouTube Data API and is subject to upstream rebase).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

import httpx

from api.v1.schemas.track_download import (
    SearchSource,
    TrackDownloadAccepted,
    TrackDownloadCandidate,
    TrackDownloadJobStatus,
    TrackDownloadSearchResponse,
)
from core.exceptions import ExternalServiceError, ResourceNotFoundError, ValidationError

if TYPE_CHECKING:
    from repositories.lidarr import LidarrRepository
    from infrastructure.cache.memory_cache import CacheInterface

logger = logging.getLogger(__name__)


VALID_LIBRARIES = frozenset({"music", "music-personal", "music-shared"})

# Cache prefixes invalidated on download completion. Mirrors constants in
# infrastructure/cache/cache_keys.py (kept as string literals here to avoid a
# circular import at this layer).
#
# Need ALL of these — clearing only source_resolution leaves upstream Lidarr
# album/track caches (5 min TTL) stale. Resolve re-fetches but then calls
# get_album_details which still returns hasFile=false from the Lidarr cache,
# so the new track keeps showing "not in library" until those TTLs expire.
_DOWNLOAD_COMPLETE_CACHE_PREFIXES = (
    "source_resolution",
    "lidarr_album_details:",
    "lidarr_album_tracks:",
    "lidarr_album_trackfiles_raw:",
    "lidarr_artist_albums:",
    "lidarr_artist_details:",
)


class TrackDownloadService:
    """Thin async proxy to the yt-dlp-worker. The library label is fixed
    at construction time and applied to every download request.

    On first-seen status=done for any job, fans out three best-effort
    actions so the new file is immediately discoverable end-to-end:
      1. Lidarr RefreshArtist (per-artist DB refresh + disk scan)
      2. Plex library/sections/<id>/refresh (so Plex indexes the file)
      3. memory_cache.clear_prefix(source_resolution) (so musicseerr's
         resolve endpoint doesn't return stale "not in library" data
         from before the file landed)

    Any single piece can fail without breaking the others — download
    success is reported regardless of post-download fan-out outcomes.
    """

    def __init__(
        self,
        *,
        worker_url: str,
        library: str,
        lidarr_repository: "LidarrRepository | None" = None,
        memory_cache: "CacheInterface | None" = None,
        plex_url: str = "",
        plex_token: str = "",
        plex_section_id: int = 0,
        timeout: float = 30.0,
    ) -> None:
        if library not in VALID_LIBRARIES:
            raise ValueError(
                f"MUSICSEERR_LIBRARY must be one of {sorted(VALID_LIBRARIES)}; got '{library}'"
            )
        self._worker_url = worker_url.rstrip("/")
        self._library = library
        self._timeout = timeout
        self._lidarr = lidarr_repository
        self._memory_cache = memory_cache
        self._plex_url = plex_url.rstrip("/")
        self._plex_token = plex_token
        self._plex_section_id = plex_section_id
        # job_id → artist_mbid, captured at request time so we can fire a
        # scoped RefreshArtist when the poll later sees status="done".
        # In-memory only — if musicseerr restarts mid-download the rescan
        # for that job is just skipped (best-effort enhancement).
        self._mbid_by_job: dict[str, str] = {}
        # job_ids we've already fired RefreshArtist for; prevents the same
        # rescan firing every poll after completion (frontend keeps polling
        # for a few cycles after status=done to confirm the final state).
        self._rescan_fired: set[str] = set()

    @property
    def library(self) -> str:
        return self._library

    async def search(
        self,
        query: str,
        limit: int = 5,
        source: SearchSource = "youtube",
    ) -> TrackDownloadSearchResponse:
        payload = {"query": query, "limit": limit, "source": source}
        data = await self._post_json("/search", payload)
        candidates = [
            TrackDownloadCandidate(
                video_id=c["video_id"],
                url=c["url"],
                title=c["title"],
                source=c.get("source", "youtube"),
                channel=c.get("channel"),
                artist=c.get("artist"),
                album=c.get("album"),
                duration_seconds=c.get("duration_seconds"),
                thumbnail_url=c.get("thumbnail_url"),
            )
            for c in data.get("candidates", [])
        ]
        return TrackDownloadSearchResponse(candidates=candidates)

    async def request_download(
        self,
        *,
        video_id: str,
        artist: str,
        album: str,
        track_title: str,
        source: SearchSource = "youtube",
        target_duration_seconds: int | None = None,
        artist_mbid: str | None,
        track_position: int | None,
        disc_number: int | None,
        user_id: str | None = None,
    ) -> TrackDownloadAccepted:
        payload: dict[str, Any] = {
            "video_id": video_id,
            "source": source,
            "target_duration_seconds": target_duration_seconds,
            "artist": artist,
            "album": album,
            "track_title": track_title,
            "artist_mbid": artist_mbid,
            "track_position": track_position,
            "disc_number": disc_number,
            "library": self._library,
            "user_id": user_id,
        }
        data = await self._post_json("/download", payload, expected_status={200, 202})
        job_id = data["job_id"]
        # Stash the mbid so we can fire a scoped Lidarr rescan on completion.
        # mbid is optional — only useful if we have a real MusicBrainz id.
        if artist_mbid:
            self._mbid_by_job[job_id] = artist_mbid
        return TrackDownloadAccepted(job_id=job_id)

    async def get_job(self, job_id: str) -> TrackDownloadJobStatus:
        data = await self._get_json(f"/jobs/{job_id}")
        status = data["status"]

        # First-seen transition to "done" → fan out three best-effort actions
        # asynchronously so the new file is discoverable end-to-end without
        # waiting on any one of them. Each is fire-and-forget; failures in
        # one don't block the others or affect the download status returned
        # to the client.
        if status == "done" and job_id not in self._rescan_fired:
            self._rescan_fired.add(job_id)
            mbid = self._mbid_by_job.pop(job_id, None)
            asyncio.create_task(self._on_download_complete(job_id, mbid))

        return TrackDownloadJobStatus(
            id=data["id"],
            status=status,
            artist=data["artist"],
            album=data["album"],
            track_title=data["track_title"],
            library=data["library"],
            file_path=data.get("file_path"),
            error=data.get("error"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    async def _on_download_complete(self, job_id: str, mbid: str | None) -> None:
        """Three-step post-download fan-out. Best-effort; any single failure
        is logged but doesn't propagate (the download itself already succeeded).
        """
        # 1. Lidarr per-artist refresh (so Lidarr DB sees the file)
        if mbid and self._lidarr is not None:
            try:
                logger.info(
                    "on_download_complete[%s]: fire Lidarr RefreshArtist mbid=%s",
                    job_id, mbid,
                )
                await self._lidarr.trigger_refresh_by_mbid(mbid)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "on_download_complete[%s]: Lidarr refresh failed: %s", job_id, e
                )
        else:
            logger.debug(
                "on_download_complete[%s]: Lidarr refresh skipped (mbid=%s lidarr=%s)",
                job_id, bool(mbid), bool(self._lidarr),
            )

        # 2. Plex section refresh (so Plex indexes the new file → Plexamp can play it)
        if self._plex_url and self._plex_token and self._plex_section_id:
            try:
                logger.info(
                    "on_download_complete[%s]: fire Plex refresh section=%d",
                    job_id, self._plex_section_id,
                )
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(
                        f"{self._plex_url}/library/sections/{self._plex_section_id}/refresh",
                        headers={"X-Plex-Token": self._plex_token},
                    )
                if r.status_code >= 300:
                    logger.warning(
                        "on_download_complete[%s]: Plex refresh returned HTTP %d",
                        job_id, r.status_code,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "on_download_complete[%s]: Plex refresh failed: %s", job_id, e
                )
        else:
            logger.debug(
                "on_download_complete[%s]: Plex refresh skipped (not configured)",
                job_id,
            )

        # 3. Invalidate musicseerr's caches — clears stale "track not in library"
        # answers AND the upstream Lidarr album/track caches that would otherwise
        # be queried after the source_resolution miss and just return stale data
        # for another 5 minutes. Over-eager: clears the entire prefix per layer,
        # not just this artist's album. Safe — caches rehydrate on demand.
        if self._memory_cache is not None:
            total = 0
            for prefix in _DOWNLOAD_COMPLETE_CACHE_PREFIXES:
                try:
                    n = await self._memory_cache.clear_prefix(prefix)
                    total += n
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "on_download_complete[%s]: cache invalidate failed for prefix %s: %s",
                        job_id, prefix, e,
                    )
            logger.info(
                "on_download_complete[%s]: cleared %d cache entries across %d prefixes",
                job_id, total, len(_DOWNLOAD_COMPLETE_CACHE_PREFIXES),
            )

    # ---- internal HTTP helpers ----

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._worker_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            logger.error("yt-dlp-worker POST %s failed: %s", path, e)
            raise ExternalServiceError(
                f"yt-dlp-worker unreachable: {e}"
            ) from e
        return self._handle_response(r, path, expected_status)

    async def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self._worker_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url)
        except httpx.HTTPError as e:
            logger.error("yt-dlp-worker GET %s failed: %s", path, e)
            raise ExternalServiceError(
                f"yt-dlp-worker unreachable: {e}"
            ) from e
        return self._handle_response(r, path)

    @staticmethod
    def _handle_response(
        r: httpx.Response,
        path: str,
        expected_status: set[int] | None = None,
    ) -> dict[str, Any]:
        if r.status_code == 404:
            raise ResourceNotFoundError(f"yt-dlp-worker {path}: not found")
        if r.status_code == 422:
            raise ValidationError(f"yt-dlp-worker {path}: invalid request: {r.text[:200]}")
        if r.status_code == 429:
            raise ValidationError("Rate limit exceeded; try again shortly")
        if expected_status is not None and r.status_code not in expected_status:
            raise ExternalServiceError(
                f"yt-dlp-worker {path}: unexpected status {r.status_code}: {r.text[:200]}"
            )
        if expected_status is None and (r.status_code < 200 or r.status_code >= 300):
            raise ExternalServiceError(
                f"yt-dlp-worker {path}: unexpected status {r.status_code}: {r.text[:200]}"
            )
        return r.json()
