from channels.generic.websocket import WebsocketConsumer

class JobConsumer(WebsocketConsumer):
    def connect(self):
        self.accept()

    def disconnect(self, close_code):
        pass

