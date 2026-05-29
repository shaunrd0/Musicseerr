/**
 * Monotonically-increasing counter that components can subscribe to in order
 * to know "the local-library state may have changed; re-fetch anything that
 * depends on it."
 *
 * Mechanism: TrackDownloadButton calls `bump()` on first-seen `status=done`
 * for a download. Components that render library-derived state (notably
 * TopSongsList's resolveMap) include `libraryRefresh.version` in their
 * effect-dependency key, so the effect re-runs when the counter ticks.
 *
 * Cheap, ephemeral (in-memory, lost on reload), and decoupled — the producer
 * (download flow) and consumers (any future component showing in-library state)
 * don't need to know about each other.
 */

function createLibraryRefreshStore() {
	let version = $state(0);

	return {
		get version(): number {
			return version;
		},

		bump(): void {
			version += 1;
		}
	};
}

export const libraryRefresh = createLibraryRefreshStore();
