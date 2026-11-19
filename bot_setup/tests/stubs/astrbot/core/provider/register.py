"""Stand-in for AstrBot's provider registry: same double-registration error as the real one."""
provider_cls_map: dict = {}


class _Meta:
    def __init__(self, type_name, desc, provider_type, cls):
        self.type, self.desc, self.provider_type, self.cls_type = type_name, desc, provider_type, cls


def register_provider_adapter(provider_type_name, desc, provider_type=None, default_config_tmpl=None,
                              provider_display_name=None):
    def deco(cls):
        if provider_type_name in provider_cls_map:
            raise ValueError(f"{provider_type_name} 已经注册")
        provider_cls_map[provider_type_name] = _Meta(provider_type_name, desc, provider_type, cls)
        return cls
    return deco
