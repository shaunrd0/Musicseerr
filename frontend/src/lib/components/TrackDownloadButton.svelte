<script lang="ts">
	import { CloudDownload, Music, X, Check, AlertTriangle, Loader2 } from 'lucide-svelte';
	import { onDestroy } from 'svelte';
	import { ApiError } from '$lib/api/client';
	import {
		searchTrackCandidates,
		requestTrackDownload,
		getTrackDownloadJob,
		TRACK_DOWNLOAD_TERMINAL_STATES,
		type TrackDownloadCandidate,
		type TrackDownloadJobStatus,
		type TrackDownloadStatus,
		type TrackDownloadSource
	} from '$lib/api/trackDownload';
	import { colors } from '$lib/colors';
	import { formatDurationSec } from '$lib/utils/formatting';
	import { libraryRefresh } from '$lib/stores/libraryRefresh.svelte';

	interface Props {
		artist: string;
		album: string;
		trackTitle: string;
		artistMbid?: string | null;
		trackPosition?: number | null;
		discNumber?: number | null;
		size?: 'sm' | 'md';
	}

	const POLL_INTERVAL_MS = 2000;
	const AUTO_CLOSE_AFTER_DONE_MS = 3000;

	let {
		artist,
		album,
		trackTitle,
		artistMbid = null,
		trackPosition = null,
		discNumber = null,
		size = 'sm'
	}: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let candidates = $state<TrackDownloadCandidate[]>([]);
	let searching = $state(false);
	let searchError = $state<string | null>(null);
	let source = $state<TrackDownloadSource>('spotify');
	let activeJobId = $state<string | null>(null);
	let jobStatus = $state<TrackDownloadJobStatus | null>(null);
	let jobError = $state<string | null>(null);
	let submitting = $state(false);
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let autoCloseTimer: ReturnType<typeof setTimeout> | null = null;

	const isJobActive = $derived(
		activeJobId !== null && (jobStatus === null || !TRACK_DOWNLOAD_TERMINAL_STATES.has(jobStatus.status))
	);
	const isJobDone = $derived(jobStatus?.status === 'done');
	const isJobFailed = $derived(jobStatus?.status === 'failed');

	function clearTimers() {
		if (pollTimer !== null) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
		if (autoCloseTimer !== null) {
			clearTimeout(autoCloseTimer);
			autoCloseTimer = null;
		}
	}

	function resetState() {
		clearTimers();
		candidates = [];
		searching = false;
		searchError = null;
		activeJobId = null;
		jobStatus = null;
		jobError = null;
		submitting = false;
	}

	async function loadCandidates() {
		searching = true;
		searchError = null;
		candidates = [];
		try {
			const query = `${artist} ${trackTitle}`.trim();
			const res = await searchTrackCandidates(query, 5, source);
			candidates = res.candidates;
			if (candidates.length === 0) {
				const label = source === 'spotify' ? 'Spotify' : 'YouTube';
				searchError = `No ${label} matches for "${query}"`;
			}
		} catch (e) {
			searchError = e instanceof ApiError ? e.message : 'Search failed';
		} finally {
			searching = false;
		}
	}

	function switchSource(next: TrackDownloadSource) {
		if (next === source || searching || submitting) return;
		source = next;
		loadCandidates();
	}

	async function pollJob() {
		if (activeJobId === null) return;
		try {
			const status = await getTrackDownloadJob(activeJobId);
			const wasTerminal =
				jobStatus !== null && TRACK_DOWNLOAD_TERMINAL_STATES.has(jobStatus.status);
			jobStatus = status;
			if (TRACK_DOWNLOAD_TERMINAL_STATES.has(status.status)) {
				if (status.status === 'done' && !wasTerminal) {
					// First-seen transition to done — tell any library-derived UI
					// (TopSongsList resolveMap etc.) to refetch. Backend caches were
					// already busted by the download-complete fan-out; this just
					// kicks the frontend out of its own per-component cache.
					libraryRefresh.bump();
					autoCloseTimer = setTimeout(() => {
						closeDialog();
					}, AUTO_CLOSE_AFTER_DONE_MS);
				}
				return;
			}
			pollTimer = setTimeout(pollJob, POLL_INTERVAL_MS);
		} catch (e) {
			jobError = e instanceof ApiError ? e.message : 'Failed to poll status';
		}
	}

	async function pickCandidate(c: TrackDownloadCandidate) {
		if (submitting || isJobActive) return;
		submitting = true;
		jobError = null;
		try {
			const res = await requestTrackDownload({
				video_id: c.video_id,
				source: c.source,
				target_duration_seconds: c.duration_seconds,
				artist,
				album,
				track_title: trackTitle,
				artist_mbid: artistMbid,
				track_position: trackPosition,
				disc_number: discNumber
			});
			activeJobId = res.job_id;
			jobStatus = null;
			pollJob();
		} catch (e) {
			jobError = e instanceof ApiError ? e.message : 'Failed to start download';
		} finally {
			submitting = false;
		}
	}

	export function openDialog() {
		if (!dialogEl) return;
		// Preserve in-flight job; only reset if previous run completed.
		if (!isJobActive && (jobStatus === null || TRACK_DOWNLOAD_TERMINAL_STATES.has(jobStatus.status))) {
			resetState();
			loadCandidates();
		}
		dialogEl.showModal();
	}

	function closeDialog() {
		if (!dialogEl) return;
		dialogEl.close();
		// If job finished (done or failed), reset on close so next open is fresh.
		if (jobStatus !== null && TRACK_DOWNLOAD_TERMINAL_STATES.has(jobStatus.status)) {
			resetState();
		}
	}

	function handleButtonClick(e: MouseEvent) {
		e.stopPropagation();
		e.preventDefault();
		openDialog();
	}

	function statusLabel(s: TrackDownloadStatus): string {
		switch (s) {
			case 'queued':
				return 'Queued';
			case 'searching':
				return 'Searching';
			case 'downloading':
				return 'Downloading';
			case 'tagging':
				return 'Tagging';
			case 'importing':
				return 'Adding to library';
			case 'done':
				return 'Done';
			case 'failed':
				return 'Failed';
			default:
				return s;
		}
	}

	onDestroy(clearTimers);
</script>

<button
	type="button"
	class="btn btn-circle btn-sm btn-ghost {size === 'sm'
		? 'min-h-[36px] min-w-[36px]'
		: 'min-h-[44px] min-w-[44px]'} border border-base-content/10 shrink-0 active:scale-[0.95]"
	title={isJobActive
		? `Track download: ${jobStatus ? statusLabel(jobStatus.status) : 'queued'}`
		: isJobDone
			? 'Downloaded'
			: isJobFailed
				? 'Last download failed — click to retry'
				: `Download "${trackTitle}"`}
	aria-label="Download {trackTitle}"
	onclick={handleButtonClick}
>
	{#if isJobActive}
		<Loader2 class="h-4 w-4 animate-spin" color={colors.accent} />
	{:else if isJobDone}
		<Check class="h-4 w-4" color={colors.accent} />
	{:else if isJobFailed}
		<AlertTriangle class="h-4 w-4 text-error" />
	{:else}
		<CloudDownload class="h-4 w-4 opacity-70" />
	{/if}
</button>

<dialog bind:this={dialogEl} class="modal">
	<div class="modal-box max-w-2xl">
		<form method="dialog">
			<button
				type="submit"
				class="btn btn-sm btn-circle btn-ghost absolute right-2 top-2"
				aria-label="Close"
				onclick={closeDialog}
			>
				<X class="h-4 w-4" />
			</button>
		</form>

		<div class="flex items-start gap-3">
			<div
				class="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg"
				style="background-color: {colors.accent}20;"
			>
				<Music class="h-6 w-6" color={colors.accent} />
			</div>
			<div class="min-w-0 flex-1">
				<div class="text-xs uppercase tracking-wide opacity-60">Download single track</div>
				<div class="truncate text-lg font-semibold">{trackTitle}</div>
				<div class="truncate text-sm opacity-70">{artist} — {album}</div>
			</div>
		</div>

		<div class="mt-3 flex justify-end">
			<div class="join" role="tablist" aria-label="Search source">
				<button
					type="button"
					role="tab"
					aria-selected={source === 'spotify'}
					class="btn btn-xs join-item {source === 'spotify' ? 'btn-active' : ''}"
					disabled={searching || submitting || isJobActive}
					onclick={() => switchSource('spotify')}
				>
					Spotify
				</button>
				<button
					type="button"
					role="tab"
					aria-selected={source === 'youtube'}
					class="btn btn-xs join-item {source === 'youtube' ? 'btn-active' : ''}"
					disabled={searching || submitting || isJobActive}
					onclick={() => switchSource('youtube')}
				>
					YouTube
				</button>
			</div>
		</div>

		<div class="divider my-3"></div>

		{#if activeJobId !== null}
			<!-- Job in progress / terminal -->
			<div class="space-y-3 py-2">
				{#if isJobDone}
					<div class="flex items-center gap-3 text-success">
						<Check class="h-6 w-6" />
						<div>
							<div class="font-semibold">Download complete</div>
							<div class="text-xs opacity-70">
								{jobStatus?.file_path ?? 'File saved'} — Plex library refresh triggered.
							</div>
						</div>
					</div>
				{:else if isJobFailed}
					<div class="flex items-start gap-3 text-error">
						<AlertTriangle class="h-6 w-6 shrink-0" />
						<div class="min-w-0">
							<div class="font-semibold">Download failed</div>
							<div class="break-words text-xs opacity-80">
								{jobStatus?.error ?? jobError ?? 'Unknown error'}
							</div>
						</div>
					</div>
				{:else}
					<div class="flex items-center gap-3">
						<Loader2 class="h-5 w-5 animate-spin" color={colors.accent} />
						<div class="text-sm">
							<span class="font-medium">{statusLabel(jobStatus?.status ?? 'queued')}</span>
							<span class="opacity-60"> — yt-dlp working on it...</span>
						</div>
					</div>
					<div class="text-xs opacity-50">
						This usually takes 20–60 seconds. You can close this dialog and the job will keep running.
					</div>
				{/if}
				{#if jobError && !isJobFailed}
					<div class="text-xs text-error">{jobError}</div>
				{/if}
			</div>
		{:else if searching}
			<div class="flex items-center gap-3 py-6">
				<span class="loading loading-spinner loading-md" style="color: {colors.accent};"></span>
				<span class="text-sm opacity-70">
					Searching {source === 'spotify' ? 'Spotify' : 'YouTube'} for matches...
				</span>
			</div>
		{:else if searchError}
			<div class="alert alert-warning text-sm">
				<AlertTriangle class="h-4 w-4" />
				{searchError}
			</div>
			<div class="mt-3 flex justify-end">
				<button type="button" class="btn btn-sm" onclick={loadCandidates}>Retry search</button>
			</div>
		{:else if candidates.length > 0}
			<div class="text-xs opacity-60">
				{#if source === 'spotify'}
					Pick a Spotify match — the worker will find the matching YouTube audio and tag it with
					Spotify metadata.
				{:else}
					Pick the best YouTube match — yt-dlp will download it to your music library.
				{/if}
			</div>
			<ul class="mt-2 space-y-1">
				{#each candidates as c (c.video_id)}
					<li>
						<button
							type="button"
							class="btn btn-block h-auto justify-start gap-3 px-3 py-2 normal-case"
							disabled={submitting}
							onclick={() => pickCandidate(c)}
						>
							{#if c.thumbnail_url}
								<img
									src={c.thumbnail_url}
									alt=""
									class="h-12 w-20 shrink-0 rounded object-cover"
									loading="lazy"
								/>
							{:else}
								<div class="h-12 w-20 shrink-0 rounded bg-base-300"></div>
							{/if}
							<div class="min-w-0 flex-1 text-left">
								<div class="truncate font-medium">{c.title}</div>
								<div class="truncate text-xs opacity-60">
									{#if c.source === 'spotify'}
										{c.artist ?? 'Unknown artist'}{#if c.album} · {c.album}{/if}
									{:else}
										{c.channel ?? 'Unknown channel'}
									{/if}
									{#if c.duration_seconds !== null} · {formatDurationSec(c.duration_seconds)}{/if}
								</div>
							</div>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>
	<form method="dialog" class="modal-backdrop">
		<button type="submit" aria-label="close" onclick={closeDialog}>close</button>
	</form>
</dialog>
