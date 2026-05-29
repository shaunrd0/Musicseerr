import { api } from '$lib/api/client';

export interface LidarrRequestPayload {
	album_mbid: string;
	track_mbid: string;
	artist_mbid?: string | null;
	track_position?: number | null;
	disc_number?: number | null;
	track_title?: string | null;
}

export interface LidarrRequestAccepted {
	status: string;
	album_id: number;
	album_title: string;
	track_id: number;
	track_title: string;
	other_tracks_unmonitored: number;
	command_id: number | null;
	note: string | null;
}

export interface LidarrRequestTrackStatus {
	recording_mbid: string;
	position: number;
	disc_number: number;
	monitored: boolean;
	has_file: boolean;
}

export interface LidarrRequestStatusResponse {
	in_library: boolean;
	tracks: LidarrRequestTrackStatus[];
}

/** The 3 persistent UI states the LidarrRequestButton can render. */
export type LidarrButtonStatus = 'none' | 'requested' | 'downloaded';

/** Project a single Lidarr per-track entry into a UI-friendly status. */
export function projectButtonStatus(
	t: LidarrRequestTrackStatus | undefined | null
): LidarrButtonStatus {
	if (!t) return 'none';
	if (t.has_file) return 'downloaded';
	if (t.monitored) return 'requested';
	return 'none';
}

/**
 * Build a status lookup over a status response.
 *
 * Indexes by both recording_mbid AND `albumMbid:position:disc` because
 * Lidarr's foreignRecordingId doesn't always equal MusicBrainz's
 * recording_id (Lidarr sometimes maps to a variant). The album_mbid is
 * baked into the position key as a safety belt so a stale lookup from
 * a previous album page can't false-positive-match the visible album's
 * tracks at the same positions (positions 1, 2, 3… collide trivially
 * across every album in existence otherwise).
 */
export function buildStatusLookup(albumMbid: string, res: LidarrRequestStatusResponse) {
	const byMbid = new Map<string, LidarrRequestTrackStatus>();
	const byPositionDisc = new Map<string, LidarrRequestTrackStatus>();
	for (const t of res.tracks) {
		if (t.recording_mbid) byMbid.set(t.recording_mbid, t);
		byPositionDisc.set(`${albumMbid}:${t.position}:${t.disc_number}`, t);
	}
	return {
		albumMbid,
		byMbid,
		byPositionDisc,
		lookup(
			lookupAlbumMbid: string,
			recordingMbid: string | null | undefined,
			position: number,
			discNumber: number
		) {
			if (recordingMbid && byMbid.has(recordingMbid)) return byMbid.get(recordingMbid);
			// Album-scope the position fallback — won't match tracks from a
			// different album even if the caller is somehow using a stale
			// lookup built for that other album.
			if (lookupAlbumMbid !== albumMbid) return undefined;
			return byPositionDisc.get(`${albumMbid}:${position}:${discNumber}`);
		}
	};
}

const ROOT = '/api/v1/lidarr-request';

export async function requestTrackViaLidarr(
	payload: LidarrRequestPayload,
	signal?: AbortSignal
): Promise<LidarrRequestAccepted> {
	return api.global.post<LidarrRequestAccepted>(ROOT, payload, { signal });
}

export async function getLidarrRequestStatus(
	albumMbid: string,
	signal?: AbortSignal
): Promise<LidarrRequestStatusResponse> {
	return api.global.get<LidarrRequestStatusResponse>(
		`${ROOT}/status?album_mbid=${encodeURIComponent(albumMbid)}`,
		{ signal }
	);
}
