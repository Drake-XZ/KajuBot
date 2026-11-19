"""Stand-in for astrbot.core.provider.provider.STTProvider."""


class STTProvider:
    def __init__(self, provider_config, provider_settings):
        self.provider_config, self.provider_settings = provider_config, provider_settings
        self.model_name = ""

    def set_model(self, name):
        self.model_name = name

    async def get_text(self, audio_url):
        raise NotImplementedError
