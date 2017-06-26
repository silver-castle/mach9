from mach9 import Mach9
from mach9.response import stream
from mach9.http import BodyChannel


data = 'abc' * 100000
app = Mach9('test_response_stream')


def test_response_stream():
    @app.post('/post/<id>', stream=True)
    async def post(request, id):
        assert isinstance(request.stream, BodyChannel)

        async def streaming(channel):
            while True:
                body_chunk = await request.stream.receive()
                if body_chunk['more_content'] is False:
                    break
                await channel.send(body_chunk['content'])
        return stream(streaming)

    request, response = app.test_client.post('/post/1', data=data)
    assert response.status == 200
    assert response.text == data
