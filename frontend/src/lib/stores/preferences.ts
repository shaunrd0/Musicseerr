import { writable } from 'svelte/store';
import type { UserPreferences, TrackButtonVisibility } from '$lib/types';
import { api } from '$lib/api/client';

const API_BASE = '/api/v1';

// All-true visibility — matches backend.TrackButtonVisibility defaults.
// Used as the client-side default so first paint (before /preferences
// resolves) renders the full cluster, matching pre-fork behavior. The
// server's response replaces this on load.
const allVisible: TrackButtonVisibility = {
	lidarr_request: true,
	track_download: true,
	preview: true,
	yt_play: true,
	jellyfin: true,
	local_files: true,
	navidrome: true,
	plex: true
};

const defaultPreferences: UserPreferences = {
	primary_types: ['album', 'ep', 'single'],
	secondary_types: ['studio'],
	release_statuses: ['official'],
	download_options: {
		popular_songs: { ...allVisible },
		album_page: { ...allVisible }
	}
};

const { subscribe, set, update } = writable<UserPreferences>(defaultPreferences);

async function loadPreferences(): Promise<void> {
	try {
		const prefs = await api.global.get<UserPreferences>(`${API_BASE}/settings/preferences`);
		set(prefs);
	} catch {
		// use defaults on fetch failure
	}
}

async function savePreferences(prefs: UserPreferences): Promise<boolean> {
	try {
		const updated = await api.global.put<UserPreferences>(
			`${API_BASE}/settings/preferences`,
			prefs
		);
		set(updated);
		return true;
	} catch {
		return false;
	}
}

export const preferencesStore = {
	subscribe,
	load: loadPreferences,
	save: savePreferences,
	update
};
