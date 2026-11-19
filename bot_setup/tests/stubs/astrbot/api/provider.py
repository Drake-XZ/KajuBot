class ProviderRequest:
    def __init__(self, system_prompt="", prompt="", contexts=None, image_urls=None):
        self.system_prompt = system_prompt
        self.prompt = prompt
        self.contexts = contexts or []
        self.image_urls = image_urls or []
        self.extra_user_content_parts = []


class LLMResponse:
    def __init__(self, t="", tools_call_name=None):
        self.completion_text = t
        self.tools_call_name = tools_call_name
