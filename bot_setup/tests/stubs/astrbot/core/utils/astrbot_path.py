import os


def get_astrbot_plugin_data_path():
    return os.environ["STUB_DATA"]


def get_astrbot_temp_path():
    path = os.path.join(os.environ["STUB_DATA"], "temp")
    os.makedirs(path, exist_ok=True)
    return path
