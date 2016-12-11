import pygame

from env import monospace
from .base_elm import BaseElm

class Button(BaseElm):
    def __init__(self, screen, **kwargs):
        self.font = kwargs.get('font', monospace)
        self.size = kwargs.get('size', 30)
        self.text = kwargs.get('text', '<Label>')
        self.color = kwargs.get('color', (246, 198, 0))
        self.clicked = kwargs.get('click', self.__clicked)
        self.click_param = kwargs.get('click_param', None)
        self.padding = kwargs.get('padding', 10)
        self.force_width = kwargs.get('force_width', None)
        self.force_height = kwargs.get('force_height', None)
        self.box = None
        self.clicking = False

        pos = kwargs.get('pos', (0, 0))
        super(Button, self).__init__(screen, pos, self.size, -1)

        self.__load_font()

    def __load_font(self):
        self.font = pygame.font.SysFont(self.font, self.size)

    def __clicked(self, param, pos):
        print "Clicked on button without handler"

    def pre_click(self, event):
        self.clicking = True
    
    def post_click(self, event):
        self.clicking = False

    def render(self, t, dt):
        if self.clicking:
            self.screen.fill(tuple(c*0.7 for c in self.color), self.box)

        elm = self.font.render(self.text, 1, self.color)
        self.screen.blit(elm, self.pos)

        top = self.pos[0] - self.padding
        left = self.pos[1] - self.padding
        width = elm.get_width() + self.padding*2
        height = elm.get_height() + self.padding*2

        if self.force_width is not None:
            width = self.force_width
            top = self.pos[0] + elm.get_width() / 2 - width / 2
        if self.force_height is not None:
            height = self.force_height
            left = self.pos[1] + elm.get_height() / 2 - height / 2

        self.box = (
            top, left,
            width, height
        )

        pygame.draw.rect(
            self.screen,
            self.color,
            self.box,
            1
        )

    def events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONUP:
                pos = event.pos
                if self.box != None and pygame.Rect(self.box).collidepoint(pos):
                    self.pre_click(event)
                    try:
                        self.clicked(self.click_param, pos)
                    finally:
                        self.post_click(event)
