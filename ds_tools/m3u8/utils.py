class Retries:
    def __init__(self, min: int = 5, max: int = 20, incr: int = 5, per_step: int = 3):
        self.delay = min
        self.max = max
        self.incr = incr
        self.per_step = per_step
        self.step_retries = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.step_retries >= self.per_step:
            if self.delay < self.max:
                self.step_retries = 0
                self.delay = min(self.delay + self.incr, self.max)
        else:
            self.step_retries += 1
        return self.delay
