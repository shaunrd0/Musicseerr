import { get, writable } from 'svelte/store';
import { api } from '$lib/api/client';
import type { HomeSettings } from '$lib/types';

const API = '/api/v1/settings/home';

interface HomeSettingsState extends HomeSettings {
	loaded: boolean;
}

const defaults: HomeSettingsState = {
	cache_ttl_trending: 3600,
	cache_ttl_personal: 300,
	show_whats_hot: true,
	show_globally_trending: true,
	show_now_playing: false,
	loaded: false
};

function createHomeSettingsStore() {
	const { subscribe, set, update } = writable<HomeSettingsState>(defaults);
	let loadPromise: Promise<void> | null = null;

	async function load(): Promise<void> {
		try {
			const settings = await api.global.get<HomeSettings>(API);
			update((state) => ({ ...state, ...settings, loaded: true }));
		} catch {
			update((state) => ({ ...state, loaded: true }));
		}
	}

	return {
		subscribe,
		load,
		refresh: load,
		ensureLoaded: async (): Promise<void> => {
			const current = get({ subscribe });
			if (current.loaded) return;
			if (loadPromise) return loadPromise;

			loadPromise = load().finally(() => {
				loadPromise = null;
			});
			return loadPromise;
		},
		get showNowPlaying(): boolean {
			return get({ subscribe }).show_now_playing;
		},
		reset: () => set(defaults)
	};
}

export const homeSettingsStore = createHomeSettingsStore();
