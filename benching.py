import pytest


def func():
    for i in range(100):
        print("|",end="")


def test_bench(benchmark):
    benchmark(func)