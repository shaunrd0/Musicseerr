<script lang="ts">
	import { getApiUrl } from '$lib/api/api-utils';
	import { preferencesStore } from '$lib/stores/preferences';
	import { integrationStore } from '$lib/stores/integration';
	import type {
		UserPreferences,
		ReleaseTypeOption,
		LidarrMetadataProfilePreferences,
		MetadataProfile,
		TrackButtonKey,
		DownloadOptionsContext
	} from '$lib/types';
	import { invalidateQueriesWithPersister } from '$lib/queries/QueryClient';
	import { ArtistQueryKeyFactory } from '$lib/queries/artist/ArtistQueryKeyFactory';

	let preferences: UserPreferences = $state({
		primary_types: [],
		secondary_types: [],
		release_statuses: [],
		// Defaults all-on — mirrors backend.TrackButtonVisibility defaults
		// and pre-fork behavior. Replaced by the server response on load.
		download_options: {
			popular_songs: {
				lidarr_request: true,
				track_download: true,
				preview: true,
				yt_play: true,
				jellyfin: true,
				local_files: true,
				navidrome: true,
				plex: true
			},
			album_page: {
				lidarr_request: true,
				track_download: true,
				preview: true,
				yt_play: true,
				jellyfin: true,
				local_files: true,
				navidrome: true,
				plex: true
			}
		}
	});
	let saving = $state(false);
	let saveMessage = $state('');

	let lidarrConfigured = $state(false);
	let lidarrProfiles: MetadataProfile[] = $state([]);
	let selectedProfileId: number | null = $state(null);
	let lidarrPrefs: LidarrMetadataProfilePreferences | null = $state(null);
	let lidarrLoading = $state(false);
	let lidarrError = $state('');
	let lidarrSyncing = $state(false);
	let lidarrMessage = $state('');
	let lidarrLoadAttempted = $state(false);

	const primaryTypes: ReleaseTypeOption[] = [
		{ id: 'album', title: 'Album', description: 'Full-length studio albums' },
		{ id: 'ep', title: 'EP', description: 'Extended Play releases (shorter than albums)' },
		{ id: 'single', title: 'Single', description: 'Individual track releases' },
		{ id: 'broadcast', title: 'Broadcast', description: 'Radio or TV broadcast recordings' },
		{ id: 'other', title: 'Other', description: 'Miscellaneous release types' }
	];

	const secondaryTypes: ReleaseTypeOption[] = [
		{ id: 'studio', title: 'Studio', description: 'Original studio recordings' },
		{ id: 'compilation', title: 'Compilation', description: 'Greatest hits and collections' },
		{ id: 'soundtrack', title: 'Soundtrack', description: 'Music from movies, games, or TV' },
		{ id: 'spokenword', title: 'Spoken Word', description: 'Audiobooks and spoken content' },
		{ id: 'interview', title: 'Interview', description: 'Interview recordings' },
		{ id: 'audio drama', title: 'Audio Drama', description: 'Dramatic audio productions' },
		{ id: 'live', title: 'Live', description: 'Live concert recordings' },
		{ id: 'remix', title: 'Remix', description: 'Remix albums' },
		{ id: 'dj-mix', title: 'DJ-mix', description: 'DJ mixed compilations' },
		{ id: 'mixtape/street', title: 'Mixtape/Street', description: 'Unofficial mixtapes' },
		{ id: 'demo', title: 'Demo', description: 'Demo recordings' }
	];

	const releaseStatuses: ReleaseTypeOption[] = [
		{
			id: 'official',
			title: 'Official',
			description: 'Officially released by the artist or label'
		},
		{ id: 'promotion', title: 'Promotion', description: 'Promotional releases' },
		{ id: 'bootleg', title: 'Bootleg', description: 'Unofficial bootleg recordings' },
		{ id: 'pseudo-release', title: 'Pseudo-Release', description: 'Placeholder or meta releases' }
	];

	// Per-button metadata for the Download Options table. `contexts` lists
	// where the button actually renders today — the toggle is hidden for
	// contexts where the button isn't rendered (e.g., the Popular Songs
	// row only shows lidarr_request + track_download). Keeping the schema
	// carrying all 8 keys in both contexts means a future expansion (e.g.
	// adding Plex playback to Popular Songs) needs no migration — just
	// flip the `contexts` array here.
	type TrackButtonOption = {
		key: TrackButtonKey;
		title: string;
		description: string;
		contexts: DownloadOptionsContext[];
	};

	// "Download" buttons — actions that pull a track into the library.
	// TrackDownloadButton already covers both YouTube and Spotify behind
	// its own source picker, so it counts as one row regardless of source.
	const downloadButtons: TrackButtonOption[] = [
		{
			key: 'lidarr_request',
			title: 'Request via Lidarr',
			description: 'Adds the track to Lidarr and triggers a search through your configured indexers.',
			contexts: ['popular_songs', 'album_page']
		},
		{
			key: 'track_download',
			title: 'Direct download (yt-dlp)',
			description:
				'Grabs the track via the yt-dlp-worker. The button itself has an internal YouTube / Spotify source picker.',
			contexts: ['popular_songs', 'album_page']
		}
	];

	// "Playback" buttons — listen / queue / play, no library write. Each
	// is still source-availability-gated (the Jellyfin button only renders
	// when a Jellyfin server is configured AND the track is mapped to a
	// file there); unchecking here force-hides on top of that gate.
	const playbackButtons: TrackButtonOption[] = [
		{
			key: 'preview',
			title: 'YouTube preview',
			description: 'Inline preview/scrub of the track on YouTube without leaving the page.',
			contexts: ['album_page']
		},
		{
			key: 'yt_play',
			title: 'YouTube play',
			description: 'Queue the track for playback via the YouTube player.',
			contexts: ['album_page']
		},
		{
			key: 'jellyfin',
			title: 'Jellyfin',
			description: 'Play the track from your Jellyfin server when available.',
			contexts: ['album_page']
		},
		{
			key: 'local_files',
			title: 'Local files',
			description: 'Play the track from the local-files library when available.',
			contexts: ['album_page']
		},
		{
			key: 'navidrome',
			title: 'Navidrome',
			description: 'Play the track from your Navidrome server when available.',
			contexts: ['album_page']
		},
		{
			key: 'plex',
			title: 'Plex',
			description: 'Play the track from your Plex server when available.',
			contexts: ['album_page']
		}
	];

	function toggleDownloadOption(context: DownloadOptionsContext, key: TrackButtonKey): void {
		// Object-spread re-assignment for Svelte 5 deep-reactivity safety —
		// matches the immutable update style used by toggleType above.
		preferences.download_options = {
			...preferences.download_options,
			[context]: {
				...preferences.download_options[context],
				[key]: !preferences.download_options[context][key]
			}
		};
	}

	function toggleType(
		category: 'primary_types' | 'secondary_types' | 'release_statuses',
		id: string
	) {
		const index = preferences[category].indexOf(id);
		if (index > -1) {
			preferences[category] = preferences[category].filter((t) => t !== id);
		} else {
			preferences[category] = [...preferences[category], id];
		}
	}

	function isLidarrEnabled(
		category: 'primary_types' | 'secondary_types' | 'release_statuses',
		id: string
	): boolean | null {
		if (!lidarrPrefs) return null;
		return lidarrPrefs[category].includes(id);
	}

	function getAllTypesForCategory(
		category: 'primary_types' | 'secondary_types' | 'release_statuses'
	): ReleaseTypeOption[] {
		if (category === 'primary_types') return primaryTypes;
		if (category === 'secondary_types') return secondaryTypes;
		return releaseStatuses;
	}

	const mismatchCount = $derived.by(() => {
		if (!lidarrPrefs) return 0;
		let count = 0;
		const categories = ['primary_types', 'secondary_types', 'release_statuses'] as const;
		for (const cat of categories) {
			for (const type of getAllTypesForCategory(cat)) {
				const msEnabled = preferences[cat].includes(type.id);
				const lrEnabled = lidarrPrefs[cat].includes(type.id);
				if (msEnabled !== lrEnabled) count++;
			}
		}
		return count;
	});

	async function loadLidarrPrefs() {
		lidarrLoadAttempted = true;
		lidarrLoading = true;
		lidarrError = '';
		try {
			if (lidarrProfiles.length === 0) {
				const profilesRes = await fetch(getApiUrl('/api/v1/settings/lidarr/metadata-profiles'));
				if (profilesRes.ok) {
					lidarrProfiles = await profilesRes.json();
				}
			}

			const params = selectedProfileId != null ? `?profile_id=${selectedProfileId}` : '';
			const response = await fetch(
				getApiUrl(`/api/v1/settings/lidarr/metadata-profile/preferences${params}`)
			);
			if (response.ok) {
				lidarrPrefs = await response.json();
				if (selectedProfileId == null && lidarrPrefs) {
					selectedProfileId = lidarrPrefs.profile_id;
				}
			} else {
				lidarrError = 'Could not load Lidarr metadata profile';
				lidarrPrefs = null;
			}
		} catch {
			lidarrError = 'Could not connect to Lidarr';
			lidarrPrefs = null;
		} finally {
			lidarrLoading = false;
		}
	}

	async function pushToLidarr() {
		lidarrSyncing = true;
		lidarrMessage = '';
		try {
			const saved = await preferencesStore.save(preferences);
			if (!saved) {
				lidarrMessage = 'Failed to save preferences before syncing to Lidarr';
				return;
			}

			const params = selectedProfileId != null ? `?profile_id=${selectedProfileId}` : '';
			const response = await fetch(
				getApiUrl(`/api/v1/settings/lidarr/metadata-profile/preferences${params}`),
				{
					method: 'PUT',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(preferences)
				}
			);
			if (response.ok) {
				lidarrPrefs = await response.json();
				lidarrMessage = 'Lidarr metadata profile updated successfully';

				await invalidateQueriesWithPersister({ queryKey: ArtistQueryKeyFactory.prefix });
				window.dispatchEvent(new CustomEvent('search-refresh'));

				setTimeout(() => {
					lidarrMessage = '';
				}, 5000);
			} else {
				try {
					const err = await response.json();
					lidarrMessage = err.error?.message || 'Failed to update Lidarr metadata profile';
				} catch {
					lidarrMessage = 'Failed to update Lidarr metadata profile';
				}
			}
		} catch {
			lidarrMessage = 'Failed to connect to Lidarr';
		} finally {
			lidarrSyncing = false;
		}
	}

	async function importFromLidarr() {
		if (!lidarrPrefs) return;
		preferences = {
			primary_types: [...lidarrPrefs.primary_types],
			secondary_types: [...lidarrPrefs.secondary_types],
			release_statuses: [...lidarrPrefs.release_statuses]
		};
		lidarrMessage = 'Imported from Lidarr — remember to save your settings';
		setTimeout(() => {
			lidarrMessage = '';
		}, 5000);
	}

	async function onProfileChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		selectedProfileId = parseInt(target.value, 10);
		lidarrPrefs = null;
		lidarrLoadAttempted = false;
		await loadLidarrPrefs();
	}

	async function handleSave() {
		saving = true;
		saveMessage = '';

		const success = await preferencesStore.save(preferences);

		if (success) {
			saveMessage = 'Saved. Artist pages and search results will refresh automatically.';

			// Invalidate artist queries since these preferences affect which releases are shown on artist pages and search results
			await invalidateQueriesWithPersister({ queryKey: ArtistQueryKeyFactory.prefix });
			window.dispatchEvent(new CustomEvent('search-refresh'));

			setTimeout(() => {
				saveMessage = '';
			}, 5000);
		} else {
			saveMessage = "Couldn't save your settings. Please try again.";
		}

		saving = false;
	}

	$effect(() => {
		preferencesStore.load();
		const unsubscribe = preferencesStore.subscribe((prefs) => {
			preferences = { ...prefs };
		});
		return unsubscribe;
	});

	$effect(() => {
		integrationStore.ensureLoaded();
		const unsubscribe = integrationStore.subscribe((status) => {
			lidarrConfigured = status.lidarr;
		});
		return unsubscribe;
	});

	$effect(() => {
		if (lidarrConfigured && !lidarrLoadAttempted) {
			loadLidarrPrefs();
		}
	});
</script>

{#snippet typeTable(
	types: ReleaseTypeOption[],
	category: 'primary_types' | 'secondary_types' | 'release_statuses'
)}
	<div class="overflow-x-auto">
		<table class="table">
			<thead>
				<tr>
					<th class="w-12 text-center">
						<span class="text-xs opacity-60">MS</span>
					</th>
					{#if lidarrConfigured && lidarrPrefs}
						<th class="w-12 text-center">
							<span class="text-xs opacity-60">Lidarr</span>
						</th>
					{/if}
					<th>Type</th>
					<th class="hidden sm:table-cell">Description</th>
				</tr>
			</thead>
			<tbody>
				{#each types as type (type.id)}
					{@const msEnabled = preferences[category].includes(type.id)}
					{@const lrEnabled = isLidarrEnabled(category, type.id)}
					{@const mismatch = lrEnabled !== null && msEnabled !== lrEnabled}
					<tr class={mismatch ? 'bg-warning/5' : ''}>
						<td class="w-12 text-center">
							<input
								type="checkbox"
								class="checkbox checkbox-primary checkbox-sm"
								checked={msEnabled}
								onchange={() => toggleType(category, type.id)}
							/>
						</td>
						{#if lidarrConfigured && lidarrPrefs}
							<td class="w-12 text-center">
								<input
									type="checkbox"
									class="checkbox checkbox-sm"
									class:checkbox-success={lrEnabled && !mismatch}
									class:checkbox-warning={mismatch}
									checked={lrEnabled ?? false}
									disabled
								/>
							</td>
						{/if}
						<td class="font-medium">
							{type.title}
							{#if mismatch}
								<span class="badge badge-warning badge-xs ml-1">differs</span>
							{/if}
						</td>
						<td class="text-base-content/70 hidden sm:table-cell">{type.description}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/snippet}

{#snippet trackButtonTable(buttons: TrackButtonOption[], context: DownloadOptionsContext)}
	{@const rows = buttons.filter((b) => b.contexts.includes(context))}
	{#if rows.length === 0}
		<p class="text-sm text-base-content/60 italic">
			(none of these buttons render in this slot today)
		</p>
	{:else}
		<div class="overflow-x-auto">
			<table class="table">
				<thead>
					<tr>
						<th class="w-12 text-center">
							<span class="text-xs opacity-60">Show</span>
						</th>
						<th>Button</th>
						<th class="hidden sm:table-cell">Description</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as btn (btn.key)}
						{@const enabled = preferences.download_options[context][btn.key]}
						<tr>
							<td class="w-12 text-center">
								<input
									type="checkbox"
									class="checkbox checkbox-primary checkbox-sm"
									checked={enabled}
									onchange={() => toggleDownloadOption(context, btn.key)}
								/>
							</td>
							<td class="font-medium">{btn.title}</td>
							<td class="text-base-content/70 hidden sm:table-cell">{btn.description}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/snippet}

<div class="card bg-base-200">
	<div class="card-body">
		<h2 class="card-title text-2xl mb-4">Included Releases</h2>
		<p class="text-base-content/70 mb-6">
			Choose which types of releases to show in artist pages and search results.
		</p>

		{#if lidarrConfigured}
			<div class="flex flex-wrap items-center gap-3 mb-6 p-3 rounded-lg bg-base-300/50">
				{#if lidarrLoading}
					<span class="loading loading-spinner loading-sm"></span>
					<span class="text-sm text-base-content/70">Loading Lidarr profile…</span>
				{:else if lidarrError}
					<span class="text-sm text-error">{lidarrError}</span>
					<button class="btn btn-ghost btn-xs" onclick={loadLidarrPrefs}>Retry</button>
				{:else if lidarrPrefs}
					<label class="flex items-center gap-2 text-sm text-base-content/70">
						Lidarr profile:
						{#if lidarrProfiles.length > 1}
							<select
								class="select select-sm select-ghost font-semibold"
								value={selectedProfileId}
								onchange={onProfileChange}
							>
								{#each lidarrProfiles as profile (profile.id)}
									<option value={profile.id}>{profile.name}</option>
								{/each}
							</select>
						{:else}
							<span class="font-semibold">{lidarrPrefs.profile_name}</span>
						{/if}
					</label>
					{#if mismatchCount > 0}
						<span class="badge badge-warning badge-sm">
							{mismatchCount} difference{mismatchCount !== 1 ? 's' : ''}
						</span>
					{:else}
						<span class="badge badge-success badge-sm">In sync</span>
					{/if}
					<div class="ml-auto flex gap-2">
						<button class="btn btn-soft btn-sm" onclick={importFromLidarr} disabled={lidarrSyncing}>
							Import from Lidarr
						</button>
						<button class="btn btn-primary btn-sm" onclick={pushToLidarr} disabled={lidarrSyncing}>
							{#if lidarrSyncing}
								<span class="loading loading-spinner loading-xs"></span>
							{/if}
							Update Lidarr
						</button>
					</div>
				{/if}
				{#if lidarrMessage}
					<div
						class="w-full mt-2 alert text-sm"
						class:alert-success={lidarrMessage.includes('success')}
						class:alert-warning={lidarrMessage.includes('remember')}
						class:alert-error={!lidarrMessage.includes('success') &&
							!lidarrMessage.includes('remember')}
					>
						<span>{lidarrMessage}</span>
					</div>
				{/if}
			</div>
		{/if}

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Primary Types</h3>
			{@render typeTable(primaryTypes, 'primary_types')}
		</div>

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Secondary Types</h3>
			{@render typeTable(secondaryTypes, 'secondary_types')}
		</div>

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Release Statuses</h3>
			{@render typeTable(releaseStatuses, 'release_statuses')}
		</div>
	</div>
</div>

<div class="card bg-base-200 mt-6">
	<div class="card-body">
		<h2 class="card-title text-2xl mb-4">Download Options</h2>
		<p class="text-base-content/70 mb-6">
			Choose which <em>download</em> buttons appear next to each track. Direct download already
			covers both YouTube and Spotify via the button's own source picker, so it counts once.
			Playback / preview buttons live in the separate card below.
		</p>

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Album Track List</h3>
			{@render trackButtonTable(downloadButtons, 'album_page')}
		</div>

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Popular Songs</h3>
			{@render trackButtonTable(downloadButtons, 'popular_songs')}
		</div>
	</div>
</div>

<div class="card bg-base-200 mt-6">
	<div class="card-body">
		<h2 class="card-title text-2xl mb-4">Playback Buttons</h2>
		<p class="text-base-content/70 mb-6">
			Choose which <em>playback</em> buttons appear next to each track. Unchecking forces a button
			hidden; checking lets the existing source-availability gate decide (e.g., the Jellyfin button
			still only renders when a Jellyfin server is configured and the track is mapped there).
		</p>

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Album Track List</h3>
			{@render trackButtonTable(playbackButtons, 'album_page')}
		</div>

		<div class="mb-8">
			<h3 class="text-xl font-semibold mb-4">Popular Songs</h3>
			{@render trackButtonTable(playbackButtons, 'popular_songs')}
		</div>
	</div>
</div>

<div class="card-actions justify-end items-center gap-4 mt-6">
	{#if saveMessage}
		<div
			class="alert flex-1"
			class:alert-success={saveMessage.includes('success')}
			class:alert-error={saveMessage.includes('Failed')}
		>
			<span>{saveMessage}</span>
		</div>
	{/if}
	<button class="btn btn-primary" onclick={handleSave} disabled={saving}>
		{#if saving}
			<span class="loading loading-spinner loading-sm"></span>
			Saving...
		{:else}
			Save Settings
		{/if}
	</button>
</div>
