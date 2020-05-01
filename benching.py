import pytest


def func():
    for i in range(10000):
        print("|",end="")


def test_bench(benchmark):
    benchmark(func)