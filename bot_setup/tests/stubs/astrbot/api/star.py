class Context:
    """Fake AstrBot Context: config + no other plugins loaded (tests can set stars / providers)."""

    def __init__(self, config=None):
        self._config = config or {"timezone": "Asia/Shanghai", "admins_id": ["111111111", "999999999"]}
        self.stars = []
        self.providers = {}
        self.stt = None

    def get_config(self, *a, **k): return self._config
    def get_all_stars(self): return self.stars
    def get_provider_by_id(self, pid): return self.providers.get(pid)
    async def get_using_provider_async(self, umo=None): return next(iter(self.providers.values()), None)
    def get_using_provider(self, umo=None): return next(iter(self.providers.values()), None)
    def get_using_stt_provider(self, umo=None): return self.stt


class Star:
    def __init__(self, context, *a, **k): self.context = context


def register(*a, **k):
    return lambda c: c
