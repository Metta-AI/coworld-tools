#!/usr/bin/env python3
from __future__ import annotations

from nim_build_support import build_nim_agents
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop
from setuptools.command.install import install
from setuptools.dist import Distribution


class _EnsureNimMixin:
    def run(self, *args, **kwargs):  # type: ignore[override]
        build_nim_agents()
        super().run(*args, **kwargs)  # type: ignore[misc]


class BuildPyCommand(_EnsureNimMixin, build_py): ...


class DevelopCommand(_EnsureNimMixin, develop): ...


class InstallCommand(_EnsureNimMixin, install): ...


class BinaryDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        return True


setup(
    cmdclass={
        "build_py": BuildPyCommand,
        "develop": DevelopCommand,
        "install": InstallCommand,
    },
    distclass=BinaryDistribution,
)
