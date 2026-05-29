"""Tests for LidarrRequestService — the single-track request orchestrator.

Regression-focused. The cross-release matching test reproduces the 2026-05-29
Gorillaz Demon Days bug: the user requested 7 specific tracks via
musicseerr-shared, Lidarr later switched the active release from the
23-track Bootleg (relId=9981) to a 15-track Official (relId=9989), and only
5/7 tracks remained monitored on the active release.

Root cause: `_request_track_locked` was matching siblings-vs-targets across
all releases by `foreignRecordingId` only. But the "same song" on different
releases of the same album frequently has DIFFERENT MusicBrainz recording
IDs (album version vs single mix vs deluxe remaster), so the matcher missed
those releases entirely. Kids With Guns and Feel Good Inc. happen to be
exactly that case — singles with their own recording UUIDs distinct from
the album recording on the bootleg.

Fix: run the same fuzzy `_find_track` chain per release using the user's
original request data (track_mbid + position + disc + title) instead of
relying on equality of release-specific recording IDs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.lidarr_request_service import LidarrRequestService, _find_track


def _track(
    track_id: int,
    title: str,
    position: int,
    *,
    disc: int = 1,
    recording_id: str | None = None,
    track_id_mb: str | None = None,
    monitored: bool = False,
) -> dict:
    return {
        "id": track_id,
        "title": title,
        "trackNumber": str(position),
        "absoluteTrackNumber": position,
        "mediumNumber": disc,
        "foreignTrackId": track_id_mb or f"trk-{track_id}",
        "foreignRecordingId": recording_id or f"rec-{track_id}",
        "monitored": monitored,
    }


def _make_repo(*, releases: list[dict], tracks_by_release: dict[int, list[dict]]) -> MagicMock:
    repo = MagicMock()
    # Album exists on first lookup (the "was_added_now=False" path — exercises
    # the additive-monitor branch, no sibling unmonitor).
    repo.get_album_by_mbid = AsyncMock(
        return_value={
            "id": 1916,
            "title": "Demon Days",
            "monitored": True,
            "artist": {"foreignArtistId": "ARTIST_MBID", "monitored": True},
        }
    )
    repo.get_album_by_id = AsyncMock(return_value={"id": 1916, "releases": releases})
    repo.get_album_tracks_raw_by_release = AsyncMock(
        side_effect=lambda rid: list(tracks_by_release.get(rid, []))
    )
    repo.set_track_monitored = AsyncMock(return_value=True)
    repo.trigger_album_search = AsyncMock(return_value={"id": 42})
    repo.update_artist_monitoring = AsyncMock()
    repo.add_album = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_cross_release_match_uses_position_disc_title_when_recording_ids_diverge():
    # Mirrors the real Gorillaz Demon Days case: one user-requested track
    # ("Feel Good Inc.") at the same position+disc on three releases but
    # with a DIFFERENT foreignRecordingId on each release (since MB has
    # separate recordings for the album version vs single vs remaster).
    target_active = _track(1001, "Feel Good Inc.", 6, recording_id="rec-active")
    target_release_b = _track(1002, "Feel Good Inc.", 6, recording_id="rec-bootleg")
    target_release_c = _track(1003, "Feel Good Inc.", 6, recording_id="rec-official")

    intro_active = _track(2001, "Intro", 1, recording_id="rec-intro-active")
    intro_b = _track(2002, "Intro", 1, recording_id="rec-intro-b")
    intro_c = _track(2003, "Intro", 1, recording_id="rec-intro-c")

    repo = _make_repo(
        releases=[
            {"id": 9989, "monitored": True},
            {"id": 9981, "monitored": False},
            {"id": 9985, "monitored": False},
        ],
        tracks_by_release={
            9989: [target_active, intro_active],
            9981: [target_release_b, intro_b],
            9985: [target_release_c, intro_c],
        },
    )

    service = LidarrRequestService(lidarr_repository=repo)

    result = await service.request_track(
        album_mbid="ALBUM_MBID",
        # The frontend sends the active-release foreignTrackId here. Other
        # releases have different track ids, so id-only matching would miss
        # them — the matcher must fall through to position+disc+title.
        track_mbid="trk-1001",
        track_position=6,
        disc_number=1,
        track_title="Feel Good Inc.",
    )

    assert result.status == "accepted"
    assert result.track_id == 1001  # target on active release

    # All three Feel Good Inc. ids must have been set monitored=True.
    # Before the fix, only 1001 (active-release recording id match) would
    # have been included.
    monitored_call_ids: set[int] = set()
    for call in repo.set_track_monitored.await_args_list:
        if call.kwargs.get("monitored") is True or (
            len(call.args) >= 2 and call.args[1] is True
        ):
            ids = call.args[0]
            for i in ids:
                monitored_call_ids.add(i)

    assert {1001, 1002, 1003}.issubset(monitored_call_ids), (
        f"target tracks across all three releases should be monitored, "
        f"got {monitored_call_ids}"
    )

    # And the siblings (Intro on each release) must NOT be in the monitored
    # set. (Verifies we didn't accidentally monitor too much.)
    assert not ({2001, 2002, 2003} & monitored_call_ids), (
        f"sibling Intro tracks should not be monitored, "
        f"got {monitored_call_ids & {2001, 2002, 2003}}"
    )


@pytest.mark.asyncio
async def test_cross_release_match_still_uses_recording_id_when_available():
    # When releases DO share the same recording id (the common case for
    # album tracks like "Last Living Souls" on Demon Days), the matcher
    # should obviously still catch them. Same shape as above but all three
    # share recording id "rec-shared".
    t_active = _track(1001, "Last Living Souls", 2, recording_id="rec-shared")
    t_b = _track(1002, "Last Living Souls", 2, recording_id="rec-shared")
    t_c = _track(1003, "Last Living Souls", 2, recording_id="rec-shared")

    repo = _make_repo(
        releases=[
            {"id": 9989, "monitored": True},
            {"id": 9981, "monitored": False},
            {"id": 9985, "monitored": False},
        ],
        tracks_by_release={9989: [t_active], 9981: [t_b], 9985: [t_c]},
    )
    service = LidarrRequestService(lidarr_repository=repo)

    await service.request_track(
        album_mbid="ALBUM_MBID",
        track_mbid="trk-1001",
        track_position=2,
        disc_number=1,
        track_title="Last Living Souls",
    )

    monitored_ids: set[int] = set()
    for call in repo.set_track_monitored.await_args_list:
        if call.kwargs.get("monitored") is True or (
            len(call.args) >= 2 and call.args[1] is True
        ):
            for i in call.args[0]:
                monitored_ids.add(i)
    assert {1001, 1002, 1003}.issubset(monitored_ids)


def test_find_track_falls_through_to_position_disc_when_ids_dont_match():
    # Direct test on the matcher: when the user-provided track_mbid does
    # NOT equal any track's foreignTrackId OR foreignRecordingId, the
    # position+disc fallback should still resolve to the right track.
    tracks = [
        _track(1, "Intro", 1),
        _track(2, "Feel Good Inc.", 6, recording_id="rec-X"),
        _track(3, "DARE", 12),
    ]
    found = _find_track(tracks, "UNRELATED-MBID", 6, 1, "Feel Good Inc.")
    assert found is tracks[1]


def test_find_track_falls_through_to_title_when_position_disc_missing():
    # And when position/disc aren't sent at all (e.g., Popular Songs
    # panel), the title-match fallback should still find it.
    tracks = [
        _track(1, "Intro", 1),
        _track(2, "Feel Good Inc.", 6, recording_id="rec-X"),
    ]
    found = _find_track(tracks, "UNRELATED-MBID", None, None, "Feel Good Inc.")
    assert found is tracks[1]
