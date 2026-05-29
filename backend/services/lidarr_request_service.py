"""LidarrRequestService — orchestrates a single-track Lidarr request.

Fork-only addition, sibling to TrackDownloadService (which proxies to
yt-dlp-worker). Where TrackDownloadService grabs a single audio file
via yt-dlp, this service uses Lidarr's full indexer + download-client
pipeline to grab the track from a release the user has configured
indexers for (slskd, qBittorrent, NZBGet, etc.).

The flow only works end-to-end when LIDARR_URL points at an instance
running the track-monitored fork (shaunrd0/Lidarr) — the PUT
/track/monitor endpoint that this service relies on returns 405 on
stock Lidarr. set_track_monitored() in the repo logs + returns False
in that case so the request still completes (album gets added, search
fires), but the user will see siblings on the album re-download too.

Race-condition handling: Lidarr's "add album" normally fires AlbumSearch
immediately. That races our unmonitor — if the grab + import complete
before we flip monitor flags, the fork's TrackMonitoredSpecification
sees all-monitored tracks and accepts the full release. We pass
search_after_add=False so Lidarr does NOT auto-search, then we set
monitor flags across ALL releases (not just the currently-active one,
since Lidarr's anyReleaseOk=true means the grab may match a release
we didn't touch), then we trigger AlbumSearch ourselves.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from typing import TYPE_CHECKING

from api.v1.schemas.lidarr_request import (
    LidarrRequestAccepted,
    LidarrRequestStatusResponse,
    LidarrRequestTrackStatus,
)
from core.exceptions import (
    ExternalServiceError,
    ResourceNotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from repositories.lidarr import LidarrRepository

logger = logging.getLogger(__name__)


# Per-album-MBID asyncio locks. Rapid clicks on N tracks of the SAME album
# serialize through the album's lock so each request sees the prior one's
# monitor flips before deciding its own unmonitor strategy. Different
# albums run in parallel as before.
#
# Bounded LRU to prevent unbounded growth — the existing per-artist lock
# pattern in repositories/lidarr/album.py uses the same shape.
_MAX_ALBUM_LOCKS = 64
_album_locks: "collections.OrderedDict[str, asyncio.Lock]" = collections.OrderedDict()


def _get_album_lock(album_mbid: str) -> asyncio.Lock:
    if album_mbid in _album_locks:
        _album_locks.move_to_end(album_mbid)
        return _album_locks[album_mbid]
    lock = asyncio.Lock()
    _album_locks[album_mbid] = lock
    # Best-effort eviction of an old unlocked entry when we exceed the cap.
    while len(_album_locks) > _MAX_ALBUM_LOCKS:
        for key in list(_album_locks.keys()):
            if not _album_locks[key].locked():
                del _album_locks[key]
                break
        else:
            break
    return lock


class LidarrRequestService:
    """Coordinate Lidarr add + selective monitor + search for a single track."""

    def __init__(self, *, lidarr_repository: "LidarrRepository") -> None:
        self._lidarr = lidarr_repository

    async def request_track(
        self,
        *,
        album_mbid: str,
        track_mbid: str,
        artist_mbid: str | None = None,
        track_position: int | None = None,
        disc_number: int | None = None,
        track_title: str | None = None,
    ) -> LidarrRequestAccepted:
        # artist_mbid is optional — Lidarr's album lookup returns the artist
        # MBID server-side, so we only need album + track for the API flow.
        if not (album_mbid and track_mbid):
            raise ValidationError("album_mbid and track_mbid are required")

        # Per-album serialization. Rapid clicks on 3 tracks from the same
        # album each acquire this lock in turn. Without it, all 3 requests
        # would race through get_album_by_mbid before any of them had a
        # chance to flip monitor flags, so all 3 would think they were the
        # "fresh add" and each would unmonitor every track that wasn't
        # their own target — leaving only the last-completed request's
        # track monitored.
        async with _get_album_lock(album_mbid):
            return await self._request_track_locked(
                album_mbid=album_mbid,
                track_mbid=track_mbid,
                track_position=track_position,
                disc_number=disc_number,
                track_title=track_title,
            )

    async def get_status(self, album_mbid: str) -> LidarrRequestStatusResponse:
        """Return per-track Lidarr-side status for an album.

        Lets the UI render the LidarrRequestButton in its persistent state
        (idle / requested / downloaded) on page load instead of resetting
        to idle on every refresh. Cheap — one /album?foreignAlbumId= and
        one /track?albumId= per call. No mutations.

        IMPORTANT: a track is reported as `monitored=true` ONLY when the
        full Lidarr chain agrees the user wants it — track + album + artist
        all monitored. Lidarr's search/grab query filters on all three, so
        a track with `track.Monitored=true` but `album.Monitored=false`
        will never actually get downloaded. Reporting just the track flag
        was misleading: an album auto-added through some other code path
        (recommendations, ListenBrainz, manual artist add) inherits the
        fork's Track.Monitored=true default on all its tracks, but with
        album/artist unmonitored Lidarr ignores them entirely — the UI
        would falsely render every track as "requested" even though the
        user never asked for them.

        has_file is independent — if the file is on disk it's on disk
        regardless of monitor state.
        """
        if not album_mbid:
            raise ValidationError("album_mbid is required")

        album = await self._lidarr.get_album_by_mbid(album_mbid)
        if not album or not album.get("id"):
            return LidarrRequestStatusResponse(in_library=False, tracks=[])

        album_monitored = bool(album.get("monitored", False))
        artist_monitored = bool((album.get("artist") or {}).get("monitored", False))
        chain_monitored = album_monitored and artist_monitored

        # Only the active release's tracks matter for the UI — the user
        # only sees one release per album page anyway.
        tracks = await self._lidarr.get_album_tracks_raw(album["id"])
        out: list[LidarrRequestTrackStatus] = []
        for t in tracks:
            recording_mbid = t.get("foreignRecordingId") or ""
            try:
                position = int(t.get("trackNumber") or t.get("absoluteTrackNumber") or 0)
            except (TypeError, ValueError):
                position = 0
            try:
                disc_number = int(t.get("mediumNumber") or 1)
            except (TypeError, ValueError):
                disc_number = 1
            track_flag = bool(t.get("monitored", False))
            out.append(
                LidarrRequestTrackStatus(
                    recording_mbid=recording_mbid,
                    position=position,
                    disc_number=disc_number,
                    # AND the chain — see docstring above.
                    monitored=track_flag and chain_monitored,
                    has_file=bool(t.get("hasFile", False)),
                )
            )
        return LidarrRequestStatusResponse(in_library=True, tracks=out)

    async def _request_track_locked(
        self,
        *,
        album_mbid: str,
        track_mbid: str,
        track_position: int | None,
        disc_number: int | None,
        track_title: str | None,
    ) -> LidarrRequestAccepted:
        # 1. Ensure album exists in Lidarr WITHOUT triggering Lidarr's auto-
        # search-on-add (which would race our unmonitor below). add_album
        # returns a wrapper dict; we re-fetch by MBID for a consistent shape.
        #
        # `was_added_now` controls the unmonitor strategy below. On a fresh
        # add every track defaults to monitored=true, so we have to unmonitor
        # siblings or Lidarr will download the whole album. If the album
        # already existed, the user (or a prior request) has already set the
        # monitor state — we preserve it and just add OUR target to the
        # monitored set, so 3 rapid clicks on Tracks A/B/C end with all
        # three monitored, not just whichever click landed last.
        album = await self._lidarr.get_album_by_mbid(album_mbid)
        was_added_now = album is None
        if was_added_now:
            logger.info("lidarr-request: album %s not in Lidarr, adding (no auto-search)", album_mbid)
            try:
                await self._lidarr.add_album(album_mbid, search_after_add=False)
            except ExternalServiceError as e:
                raise ExternalServiceError(f"Lidarr add_album failed: {e}") from e
            album = await self._lidarr.get_album_by_mbid(album_mbid)

        if not album or not album.get("id"):
            raise ExternalServiceError(
                f"Album {album_mbid} could not be added or found in Lidarr after add"
            )

        album_id = album["id"]
        album_title = album.get("title", "Unknown")

        # Ensure the artist is monitored. Lidarr's wanted/missing query (and
        # the scheduled MissingAlbumSearch) filter out tracks whose artist
        # is unmonitored, even if the tracks themselves are monitored — so
        # if a prior interaction unmonitored this artist, every track we
        # request would show as REQUESTED in our UI but Lidarr would never
        # actually search for it on its own cadence. (Our explicit
        # trigger_album_search below still fires once, but if that grab
        # doesn't land, no retry ever happens.)
        artist = album.get("artist") or {}
        artist_mbid_from_album = (
            artist.get("foreignArtistId") or artist.get("mbId")
        )
        if artist_mbid_from_album and not artist.get("monitored"):
            try:
                logger.info(
                    "lidarr-request[album %d]: monitoring artist %s (was unmonitored)",
                    album_id, artist_mbid_from_album,
                )
                await self._lidarr.update_artist_monitoring(
                    artist_mbid_from_album, monitored=True, monitor_new_items="none",
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "lidarr-request[album %d]: failed to monitor artist %s: %s",
                    album_id, artist_mbid_from_album, e,
                )

        # 2. Gather ALL tracks across every AlbumRelease. Lidarr's
        # anyReleaseOk=true means a grab can match any release of the
        # album, so we need to flip monitor flags on tracks in ALL
        # releases or the import for an unintended release sneaks past
        # our gate. The collector polls for releases since Lidarr
        # populates the releases array async after add.
        all_tracks = await self._collect_tracks_across_releases(album_id)
        if not all_tracks:
            raise ExternalServiceError(
                f"Lidarr did not populate tracks for album {album_id} within timeout"
            )

        # 3. Identify the target track on the *currently-monitored* release
        # (for the response payload). For the unmonitor step we treat ALL
        # release-instances of this recording as "target."
        active_release_tracks = [
            t for t in all_tracks if t.get("_release_monitored")
        ] or all_tracks
        target = _find_track(
            active_release_tracks, track_mbid, track_position, disc_number, track_title,
        )
        if not target:
            raise ResourceNotFoundError(
                f"Track {track_mbid} (pos={track_position}, disc={disc_number}, "
                f"title={track_title!r}) not found on Lidarr album {album_id} "
                f"({album_title})"
            )

        target_id = target["id"]
        target_title = target.get("title", "Unknown")

        # Match siblings vs targets across ALL releases using the same fuzzy
        # chain that resolved the active-release target above. Matching by
        # foreignRecordingId equality alone (the old behavior) misses songs
        # whose MB recording UUID differs across releases of the same album
        # — common for tracks released as singles with their own MB
        # recording entry distinct from the album recording. Hit us on
        # Gorillaz Demon Days 2026-05-29: the user's 7 requested tracks
        # were correctly monitored on the 23-track Bootleg (the active
        # release at request time), but only 5 carried over to the
        # 15-track Official that Lidarr later picked on import — Kids With
        # Guns and Feel Good Inc. each have a single-specific recording
        # UUID, so they silently dropped out of the monitored set when the
        # release switched. Re-running _find_track per release with the
        # user's original request data (track_mbid + position + disc +
        # title) catches them via the position+disc or title fallback even
        # when foreignRecordingId equality fails.
        tracks_by_release: dict[int | None, list[dict]] = collections.defaultdict(list)
        for t in all_tracks:
            tracks_by_release[t.get("_release_id")].append(t)

        target_ids: set[int] = set()
        for rel_tracks in tracks_by_release.values():
            match = _find_track(
                rel_tracks, track_mbid, track_position, disc_number, track_title,
            )
            if match and match.get("id"):
                target_ids.add(match["id"])

        # Defensive floor: if for some reason no cross-release match
        # resolved, at least monitor the active-release target we already
        # found. Shouldn't normally happen since _find_track succeeded on
        # the active release just above.
        if not target_ids:
            target_ids = {target_id}

        sibling_ids = [
            t["id"] for t in all_tracks
            if t.get("id") and t["id"] not in target_ids
        ]

        # 4. Set monitor flags.
        # - was_added_now=True (fresh add, everything defaults monitored=true):
        #   unmonitor siblings so they don't get downloaded.
        # - was_added_now=False (album was already in Lidarr): leave existing
        #   monitor state alone — preserves any tracks the user (or prior
        #   rapid clicks on this album) had set monitored. We just add OUR
        #   target to the monitored set on top of whatever was there.
        unmonitored_ok = True
        unmonitored_count = 0
        if was_added_now and sibling_ids:
            unmonitored_ok = await self._lidarr.set_track_monitored(sibling_ids, monitored=False)
            unmonitored_count = len(sibling_ids) if unmonitored_ok else 0

        if target_ids:
            await self._lidarr.set_track_monitored(list(target_ids), monitored=True)

        # 5. NOW trigger AlbumSearch — flags are in place, fork's import
        # specification will reject siblings regardless of which release the
        # grab matches.
        command = await self._lidarr.trigger_album_search([album_id])
        command_id = command.get("id") if command else None

        note = None
        if was_added_now and sibling_ids and not unmonitored_ok:
            note = (
                f"track unmonitor skipped (PUT /track/monitor returned non-OK; "
                f"Lidarr instance is likely not running the track-monitored fork). "
                f"Search will still fire but {len(sibling_ids)} sibling track(s) "
                f"on this album may also get downloaded."
            )
            logger.warning("lidarr-request[album %d]: %s", album_id, note)
        elif not was_added_now:
            note = (
                f"album already in Lidarr; preserved existing monitor state "
                f"and added '{target_title}' to the monitored set"
            )

        return LidarrRequestAccepted(
            status="accepted",
            album_id=album_id,
            album_title=album_title,
            track_id=target_id,
            track_title=target_title,
            other_tracks_unmonitored=unmonitored_count,
            command_id=command_id,
            note=note,
        )

    async def _collect_tracks_across_releases(self, album_id: int) -> list[dict]:
        """Fetch raw tracks for every AlbumRelease of an album.

        Returns a flat list of track dicts, each annotated with
        ``_release_monitored: bool`` so the caller can identify which
        tracks belong to the currently-active release.

        Polls /album/{id} until the `releases` array is populated —
        Lidarr fetches it async after add and a too-early read returns
        an empty list. Then iterates every release, including the active
        one, fetching raw tracks per-release via /track?albumReleaseId=.
        Using the per-release filter (rather than albumId) avoids
        depending on which release Lidarr currently flags as active.
        """
        import asyncio

        # Poll for releases — Lidarr populates them async after add.
        deadline = __import__("time").monotonic() + 30.0
        album_full = None
        releases: list[dict] = []
        while __import__("time").monotonic() < deadline:
            album_full = await self._lidarr.get_album_by_id(album_id)
            releases = (album_full or {}).get("releases") or []
            if releases:
                break
            await asyncio.sleep(1.0)

        if not releases:
            # Fallback: at least try the active-release-only fetch so the
            # caller still has something to identify the target against.
            logger.warning(
                "lidarr-request[album %d]: no releases populated within timeout; "
                "falling back to active-release-only track fetch",
                album_id,
            )
            active_only = await self._lidarr.wait_for_album_tracks_raw(
                album_id, timeout_s=30.0
            )
            # _release_id=None in fallback — caller groups tracks by it,
            # so a single None bucket Just Works.
            return [
                {**t, "_release_monitored": True, "_release_id": None}
                for t in active_only
            ]

        out: list[dict] = []
        for release in releases:
            release_id = release.get("id")
            if not release_id:
                continue
            release_tracks = await self._lidarr.get_album_tracks_raw_by_release(release_id)
            release_monitored = bool(release.get("monitored"))
            # Annotate _release_id so callers can group tracks by their
            # owning release for per-release matching (see target_ids
            # computation in _request_track_locked).
            out.extend(
                {
                    **t,
                    "_release_monitored": release_monitored,
                    "_release_id": release_id,
                }
                for t in release_tracks
            )

        if not out:
            logger.warning(
                "lidarr-request[album %d]: all %d releases returned 0 tracks",
                album_id, len(releases),
            )

        return out


def _find_track(
    tracks: list[dict],
    track_mbid: str,
    track_position: int | None,
    disc_number: int | None,
    track_title: str | None,
) -> dict | None:
    """Resolve a target track within Lidarr's track list for an album.

    Lidarr's foreignRecordingId doesn't always equal MusicBrainz's
    recording_id (Lidarr sometimes stores a release-specific variant).
    Popular Songs lists from Last.fm also don't always have position/disc
    populated. So we try four strategies in priority order; the first
    unambiguous match wins.

    Match priority:
      1. foreignTrackId == track_mbid (the MB track id, when sent)
      2. foreignRecordingId == track_mbid (the MB recording id)
      3. position + disc fallback (when both provided and exactly one match)
      4. title fallback — exact-then-substring, case-insensitive
    """
    for t in tracks:
        if t.get("foreignTrackId") == track_mbid:
            return t
    for t in tracks:
        if t.get("foreignRecordingId") == track_mbid:
            return t
    if track_position is not None and disc_number is not None:
        matches = [
            t for t in tracks
            if t.get("mediumNumber") == disc_number
            and str(t.get("trackNumber", "")) == str(track_position)
        ]
        if len(matches) == 1:
            return matches[0]
    if track_title:
        needle = track_title.strip().lower()
        # Exact case-insensitive first.
        exact = [t for t in tracks if (t.get("title") or "").strip().lower() == needle]
        if len(exact) == 1:
            return exact[0]
        # Then substring (handles "Drive My Car" vs "Drive My Car (Remastered 2009)"
        # and similar reissue annotations). Only commit if exactly one match.
        substr = [
            t for t in tracks
            if needle in (t.get("title") or "").strip().lower()
            or (t.get("title") or "").strip().lower() in needle
        ]
        if len(substr) == 1:
            return substr[0]
    return None
