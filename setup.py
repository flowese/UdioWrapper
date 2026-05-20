from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    requirements = [l.strip() for l in f if l.strip() and not l.startswith("#")]

setup(
    name="udio_wrapper",
    version="0.0.4",
    description="Generates songs using the Udio API using textual prompts.",
    author="Flowese",
    packages=find_packages(),
    install_requires=requirements,
    extras_require={
        "cloudscraper": ["cloudscraper>=1.2.0"],
    },
    python_requires=">=3.8",
)