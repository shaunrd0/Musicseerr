<script lang="ts">
	import { untrack } from 'svelte';
	import { Library, Check, AlertTriangle, Loader2, Hourglass } from 'lucide-svelte';
	import { ApiError } from '$lib/api/client';
	import { requestTrackViaLidarr, type LidarrButtonStatus } from '$lib/api/lidarrRequest';
	import { colors } from '$lib/colors';

	// LidarrButtonStatus comes from the API client module. Hydrating via
	// `initialStatus` lets the page render `requested` / `downloaded` even
	// after a refresh — without it, the button only knows transient session
	// state and forgets every prior click.

	interface Props {
		albumMbid: string;
		trackMbid: string;
		trackTitle: string;
		artistMbid?: string | null;
		trackPosition?: number | null;
		discNumber?: number | null;
		size?: 'sm' | 'md';
		initialStatus?: LidarrButtonStatus;
	}

	let {
		albumMbid,
		trackMbid,
		trackTitle,
		artistMbid = null,
		trackPosition = null,
		discNumber = null,
		size = 'sm',
		initialStatus = 'none'
	}: Props = $props();

	type ButtonState = 'idle' | 'submitting' | 'failed' | 'requested' | 'downloaded';

	// `state` is what we actually render. Hydrate from initialStatus on
	// mount, then a successful click flips us to `requested` immediately
	// (optimistic — Lidarr just confirmed it accepted the search).
	let state = $state<ButtonState>(initialStatusToState(initialStatus));
	let errorMsg = $state<string | null>(null);
	let successNote = $state<string | null>(null);

	// React to upstream initialStatus changes (e.g., page refresh re-fetched
	// the parent's status map and a track that was idle now shows as
	// downloaded because a background grab finished).
	//
	// IMPORTANT: read `state` via `untrack` so this effect only depends on
	// `initialStatus`. Without it, the optimistic flip in handleClick
	// (state = 'requested') re-fires this effect, and because the parent
	// hasn't re-polled yet `initialStatus` is still 'none', so state gets
	// reset to 'idle' and the user sees the button revert. Hit 2026-05-29
	// on Led Zeppelin — button briefly showed Hourglass then snapped back
	// to Library until a page refresh.
	//
	// Additionally, only ADOPT the parent's view if it's at least as
	// strong as our local state: idle (0) < requested (1) < downloaded (2).
	// This prevents the parent's late-arriving 'none' from downgrading
	// our just-flipped 'requested'. Upgrades (requested → downloaded)
	// still flow through normally.
	const STATE_RANK: Record<ButtonState, number> = {
		idle: 0,
		submitting: 0,
		failed: 0,
		requested: 1,
		downloaded: 2
	};
	$effect(() => {
		const incoming = initialStatusToState(initialStatus);
		untrack(() => {
			if (state === 'submitting' || state === 'failed') return;
			if (STATE_RANK[incoming] >= STATE_RANK[state]) {
				state = incoming;
			}
		});
	});

	function initialStatusToState(s: LidarrButtonStatus): ButtonState {
		switch (s) {
			case 'downloaded':
				return 'downloaded';
			case 'requested':
				return 'requested';
			default:
				return 'idle';
		}
	}

	const isReady = $derived(!!albumMbid && !!trackMbid);

	async function handleClick(e: MouseEvent) {
		e.stopPropagation();
		e.preventDefault();
		if (!isReady) return;
		// Don't fire if we already know Lidarr has it (monitored or on disk).
		// Click stays a no-op visually — the persistent icon is enough signal.
		if (state === 'requested' || state === 'downloaded' || state === 'submitting') return;
		state = 'submitting';
		errorMsg = null;
		successNote = null;
		try {
			const res = await requestTrackViaLidarr({
				album_mbid: albumMbid,
				track_mbid: trackMbid,
				artist_mbid: artistMbid,
				track_position: trackPosition,
				disc_number: discNumber,
				// Title is the last-ditch fallback for the backend matcher.
				// Lidarr's foreignRecordingId doesn't always equal MB's
				// recording_id, and Popular Songs lists often lack track
				// position/disc — title gets us through both cases.
				track_title: trackTitle
			});
			successNote = res.note;
			// Optimistic flip: Lidarr accepted, treat as requested. If a
			// later parent refetch flips us to `downloaded`, the $effect
			// above carries us there.
			state = 'requested';
		} catch (e: unknown) {
			state = 'failed';
			errorMsg = e instanceof ApiError ? e.message : 'Lidarr request failed';
			setTimeout(() => {
				if (state === 'failed') state = 'idle';
			}, 8000);
		}
	}

	const tooltip = $derived.by(() => {
		if (!isReady) return 'Missing MusicBrainz IDs — cannot request via Lidarr';
		if (state === 'submitting') return `Requesting "${trackTitle}" via Lidarr…`;
		if (state === 'downloaded') return `Already in your library — Lidarr downloaded "${trackTitle}"`;
		if (state === 'requested')
			return successNote
				? `Requested via Lidarr (${successNote}). Will appear in library when found.`
				: `Already requested in Lidarr — waiting for the next grab to land`;
		if (state === 'failed') return errorMsg ?? 'Lidarr request failed';
		return `Request "${trackTitle}" via Lidarr (uses your configured indexers)`;
	});

	// Click is only actionable in idle state. When the request is already
	// in-flight in Lidarr (or done), the icon is informational.
	const isActionable = $derived(state === 'idle' || state === 'failed');
</script>

<button
	type="button"
	class="btn btn-circle btn-sm btn-ghost {size === 'sm'
		? 'min-h-[36px] min-w-[36px]'
		: 'min-h-[44px] min-w-[44px]'} border border-base-content/10 shrink-0 active:scale-[0.95]"
	class:cursor-default={!isActionable && state !== 'submitting'}
	title={tooltip}
	aria-label="Request {trackTitle} via Lidarr"
	disabled={!isReady}
	onclick={handleClick}
>
	{#if state === 'submitting'}
		<Loader2 class="h-4 w-4 animate-spin" color={colors.accent} />
	{:else if state === 'downloaded'}
		<Check class="h-4 w-4" color={colors.accent} />
	{:else if state === 'requested'}
		<Hourglass class="h-4 w-4" color={colors.accent} />
	{:else if state === 'failed'}
		<AlertTriangle class="h-4 w-4 text-error" />
	{:else}
		<Library class="h-4 w-4 opacity-70" />
	{/if}
</button>
