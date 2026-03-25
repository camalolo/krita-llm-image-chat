import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

from krita import DockWidgetFactory, DockWidgetFactoryBase, Krita
from .llm_chat import LLMChatDocker

DOCKER_ID = "llm_image_chat_docker"

instance = Krita.instance()
factory = DockWidgetFactory(DOCKER_ID, DockWidgetFactoryBase.DockRight, LLMChatDocker)
instance.addDockWidgetFactory(factory)
