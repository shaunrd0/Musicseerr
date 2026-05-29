<script lang="ts">
	import { albumHref } from '$lib/utils/entityRoutes';
	import { Play, Disc3 } from 'lucide-svelte';
	import type { TopSong, ResolvedTrack, TrackButtonVisibility } from '$lib/types';
	import AlbumImage from './AlbumImage.svelte';
	import LastFmPlaceholder from './LastFmPlaceholder.svelte';
	import TrackPreviewButton from './TrackPreviewButton.svelte';
	import TrackDownloadButton from './TrackDownloadButton.svelte';
	import LidarrRequestButton from './LidarrRequestButton.svelte';
	import { preferencesStore } from '$lib/stores/preferences';
	import type { LidarrButtonStatus } from '$lib/api/lidarrRequest';

	interface Props {
		song: TopSong;
		position: number;
		source?: string;
		showPreview?: boolean;
		ytConfigured?: boolean;
		initialCached?: boolean | null;
		resolvedTrack?: ResolvedTrack | null;
		lidarrStatus?: LidarrButtonStatus;
		onPlay?: () => void;
	}

	let {
		song,
		position,
		source = '',
		showPreview = false,
		ytConfigured = false,
		initialCached = null,
		resolvedTrack = null,
		lidarrStatus = 'none',
		onPlay
	}: Props = $props();

	let hasAlbum = $derived(!!song.release_group_mbid);
	let isLastfmNoAlbum = $derived(!hasAlbum && source === 'lastfm');
	let canPlay = $derived(!!resolvedTrack?.source);
	let previewEnabled = $derived(showPreview && ytConfigured && !canPlay);
	// Worker requires a non-empty album for the file path; bucket release-less
	// tracks under "Singles" so the download still lands somewhere sensible.
	let downloadAlbum = $derived(song.release_name || 'Singles');

	// Subscribe to the user's per-context button-visibility preferences.
	// `popular_songs` is the relevant slot for TrackRow (used by the
	// Popular Songs panel on artist pages). Defaults all-true so first
	// paint matches pre-fork behavior; the server response replaces this
	// on load.
	let buttonVisibility = $state<TrackButtonVisibility>({
		lidarr_request: true,
		track_download: true,
		preview: true,
		yt_play: true,
		jellyfin: true,
		local_files: true,
		navidrome: true,
		plex: true
	});
	preferencesStore.subscribe((prefs) => {
		buttonVisibility = prefs.download_options.popular_songs;
	});
</script>

{#if hasAlbum}
	<div class="flex items-center gap-3 p-2 rounded-lg hover:bg-base-200 transition-colors group">
		{#if canPlay}
			<button
				onclick={onPlay}
				class="w-6 shrink-0 flex items-center justify-center cursor-pointer text-primary"
				aria-label="Play {song.title} (in library)"
				title="In library — click to play"
			>
				<Play class="w-4 h-4 mx-auto fill-current" />
			</button>
		{:else if previewEnabled}
			<span class="w-6 shrink-0 flex items-center justify-center">
				<span class="group-hover:hidden">{position}</span>
				<span class="hidden group-hover:block">
					<TrackPreviewButton
						artist={song.artist_name}
						track={song.title}
						{ytConfigured}
						{initialCached}
						size="sm"
						albumId={song.release_group_mbid ?? ''}
					/>
				</span>
			</span>
		{:else}
			<a
				href={albumHref(song.release_group_mbid ?? '')}
				class="w-6 shrink-0 flex items-center justify-center"
			>
				<span class="group-hover:hidden text-sm text-base-content/50">{position}</span>
				<span class="hidden group-hover:block">
					<Play class="w-4 h-4 mx-auto fill-current" />
				</span>
			</a>
		{/if}

		<a
			href={albumHref(song.release_group_mbid ?? '')}
			class="flex items-center gap-3 flex-1 min-w-0 cursor-pointer"
		>
			<div class="w-12 h-12 shrink-0">
				<AlbumImage
					mbid={song.release_group_mbid ?? ''}
					alt={song.release_name || ''}
					size="full"
					className="w-12 h-12 rounded"
				/>
			</div>

			<div class="flex-1 min-w-0 grid grid-cols-2 items-center gap-4">
				<p class="font-medium text-sm truncate min-w-0">{song.title}</p>
				<p class="text-xs text-base-content/60 truncate min-w-0 text-right">
					{song.release_name || ''}
				</p>
			</div>
		</a>

		<!--
			Action cluster — LidarrRequestButton + TrackDownloadButton.
			ALWAYS visible at full opacity, no hover dependency. Hover-to-reveal
			UX confused users on mobile (no hover state at all) and on desktop
			(per-user preference 2026-05-29). The "already in library" affordance
			lives in the button title attribute instead.
		-->
		<div
			class="shrink-0 flex items-center gap-1"
			title={canPlay ? 'Already in library — download again only if you need a fresh copy' : ''}
		>
			{#if buttonVisibility.lidarr_request && song.recording_mbid && song.release_group_mbid}
				<LidarrRequestButton
					albumMbid={song.release_group_mbid}
					trackMbid={song.recording_mbid}
					trackTitle={song.title}
					trackPosition={song.track_number ?? null}
					discNumber={song.disc_number ?? null}
					initialStatus={lidarrStatus}
					size="sm"
				/>
			{/if}
			{#if buttonVisibility.track_download}
				<TrackDownloadButton
					artist={song.artist_name}
					album={downloadAlbum}
					trackTitle={song.title}
					trackPosition={song.track_number ?? null}
					discNumber={song.disc_number ?? null}
					size="sm"
				/>
			{/if}
		</div>
	</div>
{:else}
	<div
		class="flex items-center gap-3 p-2 rounded-lg transition-colors group {isLastfmNoAlbum
			? 'opacity-75'
			: ''}"
	>
		{#if canPlay}
			<button
				onclick={onPlay}
				class="w-6 shrink-0 flex items-center justify-center cursor-pointer text-primary"
				aria-label="Play {song.title} (in library)"
				title="In library — click to play"
			>
				<Play class="w-4 h-4 mx-auto fill-current" />
			</button>
		{:else if previewEnabled}
			<span class="w-6 shrink-0 flex items-center justify-center">
				<span class="group-hover:hidden">{position}</span>
				<span class="hidden group-hover:block">
					<TrackPreviewButton
						artist={song.artist_name}
						track={song.title}
						{ytConfigured}
						{initialCached}
						size="sm"
					/>
				</span>
			</span>
		{:else}
			<span class="w-6 text-center text-sm text-base-content/50">{position}</span>
		{/if}

		{#if isLastfmNoAlbum}
			<LastFmPlaceholder />
		{:else}
			<div class="w-12 h-12 shrink-0 bg-base-200 rounded flex items-center justify-center">
				<Disc3 class="w-6 h-6 text-base-content/20" />
			</div>
		{/if}

		<div class="flex-1 min-w-0 grid grid-cols-2 items-center gap-4">
			<p class="font-medium text-sm truncate min-w-0">{song.title}</p>
			<p class="text-xs text-base-content/40 truncate min-w-0 text-right italic"></p>
		</div>

		<!-- Always visible at full opacity, matching the canonical cluster above. -->
		<div
			class="shrink-0"
			title={canPlay ? 'Already in library — download again only if you need a fresh copy' : ''}
		>
			{#if buttonVisibility.track_download}
				<TrackDownloadButton
					artist={song.artist_name}
					album={downloadAlbum}
					trackTitle={song.title}
					trackPosition={song.track_number ?? null}
					discNumber={song.disc_number ?? null}
					size="sm"
				/>
			{/if}
		</div>
	</div>
{/if}
