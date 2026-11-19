class Plain:
    def __init__(self, text=""): self.text = text


class Image:
    def __init__(self, url="", file="", path=""): self.url, self.file, self.path = url, file, path

    @staticmethod
    def fromURL(url): return Image(url=url, file=url)

    @staticmethod
    def fromFileSystem(path): return Image(file="file:///" + path, path=path)


class Video:
    def __init__(self, file="", url="", path=""): self.file, self.url, self.path = file, url, path

    @staticmethod
    def fromURL(url): return Video(file=url)

    @staticmethod
    def fromFileSystem(path): return Video(file="file:///" + path, path=path)

    async def convert_to_file_path(self):
        if self.path:
            return self.path
        raise FileNotFoundError(self.file)


class File:
    def __init__(self, name="", file="", url=""): self.name, self.file_, self.url = name, file, url

    async def get_file(self, allow_return_url=False): return self.file_


class Record:
    def __init__(self, file="", url=""): self.file, self.url = file, url


class Json:
    def __init__(self, data=None): self.data = data or {}


class Poke:
    def __init__(self, id="", qq=""): self.id, self.qq = id, qq


class At:
    def __init__(self, qq="", name=""): self.qq, self.name = qq, name


class Reply:
    def __init__(self, sender_id="", sender_nickname="", message_str="", chain=None, id=""):  # noqa: A002
        self.sender_id, self.sender_nickname, self.message_str = sender_id, sender_nickname, message_str
        self.chain = chain or []
        self.id = id


class Face:
    def __init__(self, id=0): self.id = id  # noqa: A002
