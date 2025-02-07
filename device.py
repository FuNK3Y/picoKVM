class Device:
    def select_input(self, input):
        pass
    
    def to_dict(self):
        result = self.__dict__.copy()
        return result
    
    @classmethod
    def from_dict(cls, data):
        return cls(**data)