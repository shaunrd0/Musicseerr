<script lang="ts">
	import type {
		AlbumBasicInfo,
		YouTubeTrackLink,
		YouTubeQuotaStatus,
		JellyfinAlbumMatch,
		JellyfinTrackInfo,
		LocalAlbumMatch,
		LocalTrackInfo,
		NavidromeAlbumMatch,
		NavidromeTrackInfo,
		PlexAlbumMatch,
		PlexTrackInfo,
		TrackButtonVisibility
	} from '$lib/types';
	import { preferencesStore } from '$lib/stores/preferences';
	import type { MenuItem } from '$lib/components/ContextMenu.svelte';
	import type { RenderedTrackSection } from './albumTrackResolvers';
	import { resolveSourceTrack } from './albumTrackResolvers';
	import { normalizeDiscNumber, getDiscTrackKey } from '$lib/player/queueHelpers';
	import { formatDuration } from '$lib/utils/formatting';
	import { colors } from '$lib/colors';
	import { playerStore } from '$lib/stores/player.svelte';
	import NowPlayingIndicator from '$lib/components/NowPlayingIndicator.svelte';
	import TrackPlayButton from '$lib/components/TrackPlayButton.svelte';
	import TrackPreviewButton from '$lib/components/TrackPreviewButton.svelte';
	import TrackSourceButton from '$lib/components/TrackSourceButton.svelte';
	import TrackDownloadButton from '$lib/components/TrackDownloadButton.svelte';
	import LidarrRequestButton from '$lib/components/LidarrRequestButton.svelte';
	import {
		getLidarrRequestStatus,
		projectButtonStatus,
		buildStatusLookup,
		type LidarrButtonStatus
	} from '$lib/api/lidarrRequest';
	import ContextMenu from '$lib/components/ContextMenu.svelte';
	import JellyfinIcon from '$lib/components/JellyfinIcon.svelte';
	import LocalFilesIcon from '$lib/components/LocalFilesIcon.svelte';
	import NavidromeIcon from '$lib/components/NavidromeIcon.svelte';
	import PlexIcon from '$lib/components/PlexIcon.svelte';

	interface Props {
		album: AlbumBasicInfo;
		renderedTrackSections: RenderedTrackSection[];
		trackLinkMap: Map<string, YouTubeTrackLink>;
		jellyfinMatch: JellyfinAlbumMatch | null;
		localMatch: LocalAlbumMatch | null;
		navidromeMatch: NavidromeAlbumMatch | null;
		plexMatch: PlexAlbumMatch | null;
		jellyfinTrackMap: Map<string, JellyfinTrackInfo>;
		localTrackMap: Map<string, LocalTrackInfo>;
		navidromeTrackMap: Map<string, NavidromeTrackInfo>;
		plexTrackMap: Map<string, PlexTrackInfo>;
		jellyfinTracks: JellyfinTrackInfo[];
		localTracks: LocalTrackInfo[];
		navidromeTracks: NavidromeTrackInfo[];
		plexTracks: PlexTrackInfo[];
		trackLinks: YouTubeTrackLink[];
		youtubeEnabled: boolean;
		youtubeApiConfigured: boolean;
		previewCacheMap: Map<string, boolean>;
		jellyfinEnabled: boolean;
		localfilesEnabled: boolean;
		navidromeEnabled: boolean;
		plexEnabled: boolean;
		onPlaySourceTrack: (
			source: 'jellyfin' | 'local' | 'navidrome' | 'plex',
			trackPosition: number,
			discNumber: number,
			title: string
		) => void;
		onTrackGenerated: (link: YouTubeTrackLink) => void;
		onQuotaUpdate: (q: YouTubeQuotaStatus) => void;
		getTrackContextMenuItems: (
			track: { position: number; disc_number?: number | null; title: string },
			resolvedLocal: LocalTrackInfo | null,
			resolvedJellyfin: JellyfinTrackInfo | null,
			resolvedNavidrome: NavidromeTrackInfo | null,
			resolvedPlex: PlexTrackInfo | null
		) => MenuItem[];
	}

	let {
		album,
		renderedTrackSections,
		trackLinkMap,
		jellyfinMatch,
		localMatch,
		navidromeMatch,
		plexMatch,
		jellyfinTrackMap,
		localTrackMap,
		navidromeTrackMap,
		plexTrackMap,
		jellyfinTracks,
		localTracks,
		navidromeTracks,
		plexTracks,
		trackLinks,
		youtubeEnabled,
		youtubeApiConfigured,
		previewCacheMap,
		jellyfinEnabled,
		localfilesEnabled,
		navidromeEnabled,
		plexEnabled,
		onPlaySourceTrack,
		onTrackGenerated,
		onQuotaUpdate,
		getTrackContextMenuItems
	}: Props = $props();

	// Lidarr per-track status. Re-fetched + polled on every album change.
	//
	// IMPORTANT: must use $effect (not onMount) for setup so the lookup
	// rebuilds when SvelteKit navigates between albums — SvelteKit reuses
	// this component across `/album/A` → `/album/B` transitions, so
	// onMount only fires once and a stale Album A lookup would leak into
	// Album B's rendering. The position+disc fallback would then collide
	// (positions 1,2,3… exist on every album) and every track on Album B
	// would falsely render as "requested in Lidarr".
	let statusLookup = $state<ReturnType<typeof buildStatusLookup> | null>(null);

	$effect(() => {
		// Reactive dep: re-run whenever the album mbid changes.
		const albumMbid = album?.musicbrainz_id;
		if (!albumMbid) {
			statusLookup = null;
			return;
		}

		// Reset the lookup BEFORE the fetch lands so buttons default to
		// idle during the transition (better than briefly showing the
		// previous album's state).
		statusLookup = null;

		let cancelled = false;
		async function refresh() {
			try {
				const res = await getLidarrRequestStatus(albumMbid);
				if (cancelled) return;
				statusLookup = buildStatusLookup(albumMbid, res);
			} catch {
				// Lidarr unreachable or album not in library — leave null.
				// Buttons fall back to `none` (idle) and remain clickable.
			}
		}

		refresh();
		const handle = setInterval(refresh, 30000);

		return () => {
			cancelled = true;
			clearInterval(handle);
		};
	});

	function statusFor(
		recordingId: string | null | undefined,
		position: number,
		disc: number
	): LidarrButtonStatus {
		if (!statusLookup) return 'none';
		const albumMbid = album?.musicbrainz_id;
		if (!albumMbid) return 'none';
		return projectButtonStatus(statusLookup.lookup(albumMbid, recordingId, position, disc));
	}

	// User's per-button visibility prefs for the album-page slot. Each
	// existing per-button render-gate (showJellyfinBtn, youtubeEnabled,
	// etc.) is AND'd with the matching flag here — unchecked = force-off,
	// checked = the existing source-availability gate decides.
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
		buttonVisibility = prefs.download_options.album_page;
	});
</script>

<div class="bg-base-200 rounded-box overflow-visible">
	<ul class="list">
		{#each renderedTrackSections as section (section.discNumber)}
			{#if renderedTrackSections.length > 1}
				<li class="list-row min-h-0 cursor-default px-3 sm:px-4 pt-4 pb-2">
					<div
						class="inline-flex items-center gap-2 rounded-full border border-base-content/10 bg-base-100/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] opacity-70"
					>
						<span class="h-1.5 w-1.5 rounded-full bg-accent"></span>
						Disc {section.discNumber}
					</div>
				</li>
			{/if}
			{#each section.items as row (row.globalIndex)}
				{@const track = row.track}
				{@const trackDiscNumber = normalizeDiscNumber(track.disc_number)}
				{@const tl = trackLinkMap.get(getDiscTrackKey(track)) ?? null}
				{@const jellyfinTrack = resolveSourceTrack(
					trackDiscNumber,
					track.position,
					row.globalIndex,
					jellyfinTrackMap,
					jellyfinTracks
				)}
				{@const localTrack = resolveSourceTrack(
					trackDiscNumber,
					track.position,
					row.globalIndex,
					localTrackMap,
					localTracks
				)}
				{@const navidromeTrack = resolveSourceTrack(
					trackDiscNumber,
					track.position,
					row.globalIndex,
					navidromeTrackMap,
					navidromeTracks
				)}
				{@const plexTrack = resolveSourceTrack(
					trackDiscNumber,
					track.position,
					row.globalIndex,
					plexTrackMap,
					plexTracks
				)}
				{@const isCurrentlyPlaying =
					playerStore.nowPlaying?.albumId === album.musicbrainz_id &&
					(playerStore.currentQueueItem?.discNumber ?? 1) === trackDiscNumber &&
					playerStore.currentQueueItem?.trackNumber === track.position &&
					playerStore.isPlaying}
				{@const showJellyfinBtn = buttonVisibility.jellyfin && jellyfinEnabled && jellyfinMatch?.found}
				{@const showLocalBtn = buttonVisibility.local_files && localfilesEnabled && localMatch?.found}
				{@const showNavidromeBtn = buttonVisibility.navidrome && navidromeEnabled && navidromeMatch?.found}
				{@const showPlexBtn = buttonVisibility.plex && plexEnabled && plexMatch?.found}
				{@const hasAnySource =
					tl !== null ||
					jellyfinTrack !== null ||
					localTrack !== null ||
					navidromeTrack !== null ||
					plexTrack !== null}
				{@const showPreview = buttonVisibility.preview && youtubeApiConfigured && !hasAnySource}
				{@const showYtPlay = buttonVisibility.yt_play && youtubeEnabled}
				{@const showLidarrRequest = buttonVisibility.lidarr_request && !!track.recording_id}
				{@const showTrackDownload = buttonVisibility.track_download}
				<li
					class="list-row group hover:bg-base-300/50 transition-colors p-3 sm:p-4"
					style={isCurrentlyPlaying ? `background-color: ${colors.accent}20;` : ''}
				>
					<!--
					  flex-wrap so the action cluster (up to 9 buttons: preview /
					  play / 4 source icons / lidarr-request / download / context-menu)
					  drops to a second line on narrow mobile viewports instead of
					  squeezing the track title to zero width via the cluster's
					  shrink-0.
					-->
					<div class="list-col-grow flex flex-wrap items-center gap-x-4 gap-y-2 w-full">
						<div
							class="font-medium w-8 text-center shrink-0 {isCurrentlyPlaying
								? ''
								: 'text-base-content/60'}"
							style={isCurrentlyPlaying ? `color: ${colors.accent};` : ''}
						>
							{#if isCurrentlyPlaying}
								<NowPlayingIndicator />
							{:else}
								{track.position}
							{/if}
						</div>

						<div class="flex-1 min-w-[10rem]">
							<div
								class="font-medium truncate"
								style={isCurrentlyPlaying ? `color: ${colors.accent};` : ''}
							>
								{track.title}
							</div>
						</div>

						<div class="text-base-content/60 text-sm shrink-0">
							{formatDuration(track.length)}
						</div>

						<div class="flex flex-wrap items-center gap-1.5 sm:shrink-0 sm:ml-auto justify-end">
								{#if showPreview}
									<TrackPreviewButton
										artist={album.artist_name}
										track={track.title}
										ytConfigured={youtubeApiConfigured}
										initialCached={previewCacheMap.get(
											`${album.artist_name.toLowerCase()}|${track.title.toLowerCase()}`
										) ?? null}
										albumId={album.musicbrainz_id}
										coverUrl={album.cover_url ?? null}
										artistId={album.artist_id}
									/>
								{/if}

								{#if showYtPlay}
									<TrackPlayButton
										trackNumber={track.position}
										discNumber={trackDiscNumber}
										trackName={track.title}
										trackLink={tl}
										allTrackLinks={trackLinks}
										albumId={album.musicbrainz_id}
										albumName={album.title}
										artistName={album.artist_name}
										coverUrl={album.cover_url ?? null}
										artistId={album.artist_id}
										apiConfigured={youtubeApiConfigured}
										onGenerated={onTrackGenerated}
										{onQuotaUpdate}
									/>
								{/if}

								{#if showJellyfinBtn}
									<TrackSourceButton
										available={jellyfinTrack !== null}
										sourceColor="rgb(var(--brand-jellyfin))"
										onclick={() =>
											onPlaySourceTrack('jellyfin', track.position, trackDiscNumber, track.title)}
										ariaLabel={jellyfinTrack ? 'Play on Jellyfin' : 'Not available on Jellyfin'}
									>
										{#snippet icon()}
											<JellyfinIcon class="h-4 w-4" />
										{/snippet}
									</TrackSourceButton>
								{/if}

								{#if showLocalBtn}
									<TrackSourceButton
										available={localTrack !== null}
										sourceColor="rgb(var(--brand-localfiles))"
										onclick={() =>
											onPlaySourceTrack('local', track.position, trackDiscNumber, track.title)}
										ariaLabel={localTrack ? 'Play local file' : 'Not available locally'}
									>
										{#snippet icon()}
											<LocalFilesIcon class="h-4 w-4" />
										{/snippet}
									</TrackSourceButton>
								{/if}

								{#if showNavidromeBtn}
									<TrackSourceButton
										available={navidromeTrack !== null}
										sourceColor="rgb(var(--brand-navidrome))"
										onclick={() =>
											onPlaySourceTrack('navidrome', track.position, trackDiscNumber, track.title)}
										ariaLabel={navidromeTrack ? 'Play on Navidrome' : 'Not available on Navidrome'}
									>
										{#snippet icon()}
											<NavidromeIcon class="h-4 w-4" />
										{/snippet}
									</TrackSourceButton>
								{/if}

								{#if showPlexBtn}
									<TrackSourceButton
										available={plexTrack !== null}
										sourceColor="rgb(var(--brand-plex))"
										onclick={() =>
											onPlaySourceTrack('plex', track.position, trackDiscNumber, track.title)}
										ariaLabel={plexTrack ? 'Play on Plex' : 'Not available on Plex'}
									>
										{#snippet icon()}
											<PlexIcon class="h-4 w-4" />
										{/snippet}
									</TrackSourceButton>
								{/if}

								{#if showLidarrRequest}
									<LidarrRequestButton
										albumMbid={album.musicbrainz_id}
										trackMbid={track.recording_id}
										trackTitle={track.title}
										artistMbid={album.artist_id}
										trackPosition={track.position}
										discNumber={trackDiscNumber}
										initialStatus={statusFor(track.recording_id, track.position, trackDiscNumber)}
									/>
								{/if}

								{#if showTrackDownload}
									<TrackDownloadButton
										artist={album.artist_name}
										album={album.title}
										trackTitle={track.title}
										artistMbid={album.artist_id}
										trackPosition={track.position}
										discNumber={trackDiscNumber}
									/>
								{/if}

								<div>
									<ContextMenu
										items={getTrackContextMenuItems(
											track,
											localTrack,
											jellyfinTrack,
											navidromeTrack,
											plexTrack
										)}
										position="end"
										size="xs"
									/>
								</div>
							</div>
					</div>
				</li>
			{/each}
		{/each}
	</ul>
</div>
