import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { writable } from 'svelte/store';

vi.mock('$env/dynamic/public', () => ({
	env: { PUBLIC_API_URL: '' }
}));

// integrationStore needs to be a real Svelte store — nowPlayingSessions uses
// `get(integrationStore)` to decide which sources to poll.
const integrationState = writable({
	jellyfin: false,
	navidrome: false,
	plex: true,
	loaded: true
});
vi.mock('$lib/stores/integration', () => ({
	integrationStore: integrationState
}));

let showNowPlaying = false;
vi.mock('$lib/stores/homeSettings.svelte', () => ({
	homeSettingsStore: {
		get showNowPlaying() {
			return showNowPlaying;
		}
	}
}));

describe('nowPlayingStore privacy gate', () => {
	let originalFetch: typeof globalThis.fetch;

	beforeEach(() => {
		originalFetch = globalThis.fetch;
		Object.defineProperty(document, 'hidden', { value: false, configurable: true });
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
		vi.resetModules();
	});

	it('skips the network when showNowPlaying is false', async () => {
		showNowPlaying = false;
		const fetchSpy = vi.fn();
		globalThis.fetch = fetchSpy;

		const { nowPlayingStore } = await import('./nowPlayingSessions.svelte');
		await nowPlayingStore.refresh();

		expect(fetchSpy).not.toHaveBeenCalled();
		expect(nowPlayingStore.sessions.length).toBe(0);
	});

	it('hits the configured source when showNowPlaying is true', async () => {
		showNowPlaying = true;
		const fetchSpy = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ sessions: [] }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			})
		);
		globalThis.fetch = fetchSpy;

		const { nowPlayingStore } = await import('./nowPlayingSessions.svelte');
		await nowPlayingStore.refresh();

		// Plex is the only integration configured in the mock above — exactly
		// one fetch should land on the Plex sessions endpoint.
		expect(fetchSpy).toHaveBeenCalledTimes(1);
		expect(String(fetchSpy.mock.calls[0][0])).toContain('plex');
	});
});
