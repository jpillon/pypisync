#!/usr/bin/env python3
import functools
import pickle
import os


class Memoize:
    _cache = {}
    _persistent_cache = {}
    filename = ".memoize_cache"

    def __init__(self, persistent=False):
        self._persistent = persistent

    def __call__(self, func):
        if self._persistent:
            cache = self._persistent_cache
        else:
            cache = self._cache
        cache[func.__name__] = {}

        @functools.wraps(func)
        def decorator(*args, **kwargs):
            key = repr((args, kwargs))

            if func.__name__ not in cache:
                cache[func.__name__] = {}
            if key not in cache[func.__name__]:
                cache[func.__name__][key] = func(*args, **kwargs)
            return cache[func.__name__][key]

        return decorator

    @classmethod
    def load(cls):
        if os.path.exists(cls.filename):
            with open(cls.filename, "rb") as f:
                cls._persistent_cache = pickle.load(f)

    @classmethod
    def save(cls):
        with open(cls.filename, "wb") as f:
            pickle.dump(cls._persistent_cache, f)


memoize = Memoize
