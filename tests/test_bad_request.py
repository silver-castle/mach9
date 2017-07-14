import asyncio
from mach9 import Mach9


def test_bad_request_response():
    app = Mach9('test_bad_request_response')
    lines = []

    @app.listener('after_server_start')
    async def _request(mach9, loop):
        connect = asyncio.open_connection('127.0.0.1', 42101)
        reader, writer = await connect
        writer.write(b'not http')
        while True:
            line = await reader.readline()
            if not line:
                break
            lines.append(line)
        app.stop()
    app.run(host='127.0.0.1', port=42101)
    assert lines[0] == b'HTTP/1.1 400 Bad Request\r\n'
    assert lines[-1] == b'Error: Bad Request'
