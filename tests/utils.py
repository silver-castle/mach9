class Transport:

    def get_extra_info(self, name):
        if name == 'peername':
            return ('127.0.0.1', 1234)
        elif name == 'sockname':
            return ('127.0.0.1', 5678)
