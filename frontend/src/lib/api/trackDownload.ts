import { api } from '$lib/api/client';

export type TrackDownloadStatus =
	| 'queued'
	| 'searching'
	| 'downloading'
	| 'tagging'
	| 'importing'
	| 'done'
	| 'failed';

export type TrackDownloadSource = 'youtube' | 'spotify';

export const TRACK_DOWNLOAD_TERMINAL_STATES: ReadonlySet<TrackDownloadStatus> = new Set([
	'done',
	'failed'
]);

export interface TrackDownloadCandidate {
	video_id: string;
	url: string;
	title: string;
	source: TrackDownloadSource;
	channel: string | null;
	artist: string | null;
	album: string | null;
	duration_seconds: number | null;
	thumbnail_url: string | null;
}

export interface TrackDownloadSearchResponse {
	candidates: TrackDownloadCandidate[];
}

export interface TrackDownloadRequestPayload {
	video_id: string;
	artist: string;
	album: string;
	track_title: string;
	source?: TrackDownloadSource;
	target_duration_seconds?: number | null;
	artist_mbid?: string | null;
	track_position?: number | null;
	disc_number?: number | null;
}

export interface TrackDownloadAccepted {
	job_id: string;
}

export interface TrackDownloadJobStatus {
	id: string;
	status: TrackDownloadStatus;
	artist: string;
	album: string;
	track_title: string;
	library: string;
	created_at: string;
	updated_at: string;
	file_path: string | null;
	error: string | null;
}

const ROOT = '/api/v1/track-download';

export async function searchTrackCandidates(
	query: string,
	limit = 5,
	source: TrackDownloadSource = 'youtube',
	signal?: AbortSignal
): Promise<TrackDownloadSearchResponse> {
	return api.global.post<TrackDownloadSearchResponse>(
		`${ROOT}/search`,
		{ query, limit, source },
		{ signal }
	);
}

export async function requestTrackDownload(
	payload: TrackDownloadRequestPayload,
	signal?: AbortSignal
): Promise<TrackDownloadAccepted> {
	return api.global.post<TrackDownloadAccepted>(ROOT, payload, { signal });
}

export async function getTrackDownloadJob(
	jobId: string,
	signal?: AbortSignal
): Promise<TrackDownloadJobStatus> {
	return api.global.get<TrackDownloadJobStatus>(`${ROOT}/${jobId}`, { signal });
}
