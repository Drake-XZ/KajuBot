class TextPart:
    def __init__(self, text=""):
        self.text = text
        self.type = "text"
        self._no_save = False

    def mark_as_temp(self):
        self._no_save = True
        return self
