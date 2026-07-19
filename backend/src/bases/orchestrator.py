from abc import abstractmethod, ABC


class BaseOrchestrator(ABC):
    def __init__(self):
        super().__init__()

    @abstractmethod
    def run():
        ...