class Device:
    def set_active_input(self, input):
        pass

    def to_dict(self):
        return {key: value for key, value in self.__dict__.items() if not key.startswith("_")}

    @classmethod
    def from_dict(cls, data):
        return cls(**data)
