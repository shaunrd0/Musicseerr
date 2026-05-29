"""Single-track Lidarr request API. Fork-only addition.

Distinct from track_download (yt-dlp-worker proxy). This route asks the
configured Lidarr instance to add the album and grab JUST the requested
track via its native indexer pipeline, relying on the track-monitored
fork to gate the import so siblings don't land on disk.

Requires LIDARR_URL pointed at a fork instance (currently
lidarr-shared on gnat:8688).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.v1.schemas.lidarr_request import (
    LidarrRequestAccepted,
    LidarrRequestRequest,
    LidarrRequestStatusResponse,
)
from core.dependencies import get_lidarr_request_service
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from services.lidarr_request_service import LidarrRequestService

router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/lidarr-request",
    tags=["lidarr-request"],
)


@router.post("", response_model=LidarrRequestAccepted, status_code=202)
async def request_track_via_lidarr(
    body: LidarrRequestRequest = MsgSpecBody(LidarrRequestRequest),
    service: LidarrRequestService = Depends(get_lidarr_request_service),
) -> LidarrRequestAccepted:
    return await service.request_track(
        album_mbid=body.album_mbid,
        track_mbid=body.track_mbid,
        artist_mbid=body.artist_mbid,
        track_position=body.track_position,
        disc_number=body.disc_number,
        track_title=body.track_title,
    )


@router.get("/status", response_model=LidarrRequestStatusResponse)
async def get_lidarr_request_status(
    album_mbid: str = Query(..., description="Album MusicBrainz release-group ID"),
    service: LidarrRequestService = Depends(get_lidarr_request_service),
) -> LidarrRequestStatusResponse:
    return await service.get_status(album_mbid)
