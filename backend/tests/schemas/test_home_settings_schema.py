from api.v1.schemas.settings import HomeSettings


class TestHomeSettingsDefaults:
    def test_show_now_playing_defaults_off(self) -> None:
        # Default off: Plex /status/sessions returns sessions across the whole
        # server with no library-section filter, so a shared instance leaks
        # every household member's listening activity. The privacy default
        # must be off — opt-in per instance.
        assert HomeSettings().show_now_playing is False

    def test_show_whats_hot_default_unchanged(self) -> None:
        assert HomeSettings().show_whats_hot is True

    def test_show_globally_trending_default_unchanged(self) -> None:
        assert HomeSettings().show_globally_trending is True
