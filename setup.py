import os
from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    requirements = f.read().splitlines()

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name='udio_wrapper',
    version='0.0.5',
    description='Generates songs using the Udio API using textual prompts.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Flowese',
    packages=find_packages(),
    python_requires='>=3.8',
    install_requires=requirements,
)
