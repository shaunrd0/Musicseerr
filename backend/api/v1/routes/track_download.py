"""Inline track-download API. Fork-only addition.

Proxies to the yt-dlp-worker sidecar on gnat. The library label is fixed by
backend env (MUSICSEERR_LIBRARY) — clients cannot override it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.v1.schemas.track_download import (
    TrackDownloadAccepted,
    TrackDownloadJobStatus,
    TrackDownloadRequest,
    TrackDownloadSearchRequest,
    TrackDownloadSearchResponse,
)
from core.dependencies import get_track_download_service
from infrastructure.msgspec_fastapi import MsgSpecBody, MsgSpecRoute
from services.track_download_service import TrackDownloadService

router = APIRouter(
    route_class=MsgSpecRoute,
    prefix="/track-download",
    tags=["track-download"],
)


@router.post("/search", response_model=TrackDownloadSearchResponse)
async def search_candidates(
    body: TrackDownloadSearchRequest = MsgSpecBody(TrackDownloadSearchRequest),
    service: TrackDownloadService = Depends(get_track_download_service),
) -> TrackDownloadSearchResponse:
    return await service.search(query=body.query, limit=body.limit, source=body.source)


@router.post("", response_model=TrackDownloadAccepted, status_code=202)
async def request_track_download(
    body: TrackDownloadRequest = MsgSpecBody(TrackDownloadRequest),
    service: TrackDownloadService = Depends(get_track_download_service),
) -> TrackDownloadAccepted:
    return await service.request_download(
        video_id=body.video_id,
        source=body.source,
        target_duration_seconds=body.target_duration_seconds,
        artist=body.artist,
        album=body.album,
        track_title=body.track_title,
        artist_mbid=body.artist_mbid,
        track_position=body.track_position,
        disc_number=body.disc_number,
    )


@router.get("/{job_id}", response_model=TrackDownloadJobStatus)
async def get_track_download_job(
    job_id: str,
    service: TrackDownloadService = Depends(get_track_download_service),
) -> TrackDownloadJobStatus:
    return await service.get_job(job_id)
