class ToolSet:
    def __init__(self, tools=None): self.tools = list(tools or [])
    def add_tool(self, tool): self.tools.append(tool)
    def names(self): return [t.name for t in self.tools]
    def remove_tool(self, name): self.tools = [t for t in self.tools if t.name != name]
    def get_tool(self, name): return next((t for t in self.tools if t.name == name), None)
