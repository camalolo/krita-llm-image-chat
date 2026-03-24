from krita import DockWidgetFactory, DockWidgetFactoryBase, Krita
from .llm_chat import LLMChatDocker

DOCKER_ID = "llm_image_chat_docker"

# Register the docker with Krita
instance = Krita.instance()
factory = DockWidgetFactory(DOCKER_ID, DockWidgetFactoryBase.DockRight, LLMChatDocker)
instance.addDockWidgetFactory(factory)
