import pytest


def func():
    for i in range(1000):
        print("|",end="")


def test_bench(benchmark):
    benchmark(func)