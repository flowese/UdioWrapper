from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    requirements = f.read().splitlines()

setup(
    name='udio_wrapper',
    version='0.0.4',
    description='Generates songs using the Udio API using textual prompts.',
    author='Flowese',
    packages=find_packages(),
    install_requires=requirements,
)
