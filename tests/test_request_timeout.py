from mach9 import Mach9
import asyncio
from mach9.response import text
from mach9.config import Config

Config.REQUEST_TIMEOUT = 1
request_timeout_app = Mach9('test_request_timeout')
request_timeout_default_app = Mach9('test_request_timeout_default')


@request_timeout_default_app.route('/1')
async def handler_2(request):
    await asyncio.sleep(2)
    return text('OK')


def test_default_server_error_request_timeout():
    request, response = request_timeout_default_app.test_client.get('/1')
    assert response.status == 408
    assert response.text == 'Error: Request Timeout'
