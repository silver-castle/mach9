from json import loads as json_loads, dumps as json_dumps
from mach9 import Mach9
from mach9.response import json, text


# ------------------------------------------------------------ #
#  UTF-8
# ------------------------------------------------------------ #

def test_utf8_query_string():
    app = Mach9('test_utf8_query_string')

    @app.route('/')
    async def handler(request):
        return text('OK')

    request, response = app.test_client.get('/', params=[("utf8", '✓')])
    assert request.args.get('utf8') == '✓'


def test_utf8_response():
    app = Mach9('test_utf8_response')

    @app.route('/')
    async def handler(request):
        return text('✓')

    request, response = app.test_client.get('/')
    assert response.text == '✓'


def skip_test_utf8_route():
    app = Mach9('skip_test_utf8_route')

    @app.route('/')
    async def handler(request):
        return text('OK')

    # UTF-8 Paths are not supported
    request, response = app.test_client.get('/✓')
    assert response.text == 'OK'


def test_utf8_post_json():
    app = Mach9('test_utf8_post_json')

    @app.route('/')
    async def handler(request):
        return text('OK')

    payload = {'test': '✓'}
    headers = {'content-type': 'application/json'}

    request, response = app.test_client.get(
        '/',
        data=json_dumps(payload), headers=headers)

    assert request.json.get('test') == '✓'
    assert response.text == 'OK'
