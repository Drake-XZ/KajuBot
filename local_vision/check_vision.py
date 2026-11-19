"""Live image and GPU smoke check; image bytes remain in memory."""
import base64
import json
import struct
import time
import urllib.request
import zlib
from pathlib import Path

URL = 'http://127.0.0.1:11435'
MODEL = 'qwen3-vl:4b-instruct'


def api(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(URL + path, data, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def test_image():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))

    rows = bytearray()
    for y in range(320):
        rows.append(0)
        for x in range(640):
            if 60 <= x < 230 and 75 <= y < 245:
                rows.extend((255, 0, 0))
            elif (x - 470) ** 2 + (y - 160) ** 2 < 85 ** 2:
                rows.extend((0, 0, 255))
            else:
                rows.extend((255, 255, 255))
    header = struct.pack('!IIBBBBB', 640, 320, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def main():
    version = api('/api/version')['version']
    tags = api('/api/tags')['models']
    assert any(item['name'] == MODEL for item in tags), 'Required local model is missing'
    image = base64.b64encode(test_image()).decode()
    prompt = ('Identify all large colored shapes in the image. Return JSON with an objects array; '
              'each object has color, shape (square, circle, or triangle), and position (left or right). '
              'Use lowercase English. Ignore the background.')
    schema = {'type': 'object', 'properties': {'objects': {'type': 'array', 'items': {
        'type': 'object', 'properties': {key: {'type': 'string'} for key in ('color', 'shape', 'position')},
        'required': ['color', 'shape', 'position']}}}, 'required': ['objects']}
    started = time.monotonic()
    response = api('/api/chat', {'model': MODEL, 'stream': False, 'format': schema,
        'keep_alive': '2m', 'options': {'num_ctx': 8192, 'num_predict': 160, 'temperature': 0},
        'messages': [{'role': 'user', 'content': prompt, 'images': [image]}]})
    native_seconds = time.monotonic() - started
    native = json.loads(response['message']['content'])
    assert_shapes(native)
    started = time.monotonic()
    compatible = api('/v1/chat/completions', {'model': MODEL, 'stream': False,
        'temperature': 0, 'max_tokens': 160, 'response_format': {'type': 'json_object'},
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + image}}]}]})
    compatible_seconds = time.monotonic() - started
    assert_shapes(json.loads(compatible['choices'][0]['message']['content']))
    loaded = api('/api/ps')['models']
    model = next(item for item in loaded if item['name'] == MODEL)
    assert model['size_vram'] > 0, 'Model did not use GPU memory'
    evidence = {'version': version, 'model': MODEL, 'url': URL,
        'native_seconds': round(native_seconds, 3), 'openai_seconds': round(compatible_seconds, 3),
        'image_facts': native, 'loaded_size_bytes': model['size'], 'gpu_size_bytes': model['size_vram'],
        'context_length': model.get('context_length'), 'model_digest': model['digest']}
    (Path(__file__).parent / 'logs' / 'vision-check.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))


def assert_shapes(result):
    facts = {(item['color'].lower(), item['shape'].lower(), item['position'].lower()) for item in result['objects']}
    assert facts == {('red', 'square', 'left'), ('blue', 'circle', 'right')}, f'Incorrect image facts: {facts}'


if __name__ == '__main__':
    main()
